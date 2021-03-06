#!/usr/bin/env python3

from collections import OrderedDict

import cimodel.dimensions as dimensions
import cimodel.miniutils as miniutils
from cimodel.conf_tree import Ver


DOCKER_IMAGE_PATH_BASE = "308535385114.dkr.ecr.us-east-1.amazonaws.com/caffe2/"

DOCKER_IMAGE_VERSION = 248


CONFIG_HIERARCHY = [
    (Ver("ubuntu", "14.04"), [
        (Ver("gcc", "4.8"), ["py2"]),
        (Ver("gcc", "4.9"), ["py2"]),
    ]),
    (Ver("ubuntu", "16.04"), [
        (Ver("cuda", "8.0"), ["py2"]),
        (Ver("cuda", "9.0"), [
            # TODO make explicit that this is a "secret TensorRT build"
            #  (see https://github.com/pytorch/pytorch/pull/17323#discussion_r259446749)
            "py2",
            "cmake",
        ]),
        (Ver("cuda", "9.1"), ["py2"]),
        (Ver("mkl"), ["py2"]),
        (Ver("gcc", "5"), ["onnx_py2"]),
        (Ver("clang", "3.8"), ["py2"]),
        (Ver("clang", "3.9"), ["py2"]),
        (Ver("clang", "7"), ["py2"]),
        (Ver("android"), ["py2"]),
    ]),
    (Ver("centos", "7"), [
        (Ver("cuda", "9.0"), ["py2"]),
    ]),
    (Ver("macos", "10.13"), [
        # TODO ios and system aren't related. system qualifies where the python comes
        #  from (use the system python instead of homebrew or anaconda)
        (Ver("ios"), ["py2"]),
        (Ver("system"), ["py2"]),
    ]),
]


class Conf(object):
    def __init__(self, language, distro, compiler, phase):

        self.language = language
        self.distro = distro
        self.compiler = compiler
        self.phase = phase

    def is_build_only(self):
        return str(self.compiler) in [
            "gcc4.9",
            "clang3.8",
            "clang3.9",
            "clang7",
            "android",
        ] or self.get_platform() == "macos"

    # TODO: Eventually we can probably just remove the cudnn7 everywhere.
    def get_cudnn_insertion(self):

        omit = self.language == "onnx_py2" \
            or self.compiler.name in ["android", "mkl", "clang"] \
            or str(self.distro) in ["ubuntu14.04", "macos10.13"]

        return [] if omit else ["cudnn7"]

    def get_build_name_root_parts(self):
        return [
            "caffe2",
            self.language,
        ] + self.get_build_name_middle_parts()

    def get_build_name_middle_parts(self):
        return [str(self.compiler)] + self.get_cudnn_insertion() + [str(self.distro)]

    def construct_phase_name(self, phase):
        root_parts = self.get_build_name_root_parts()
        return "_".join(root_parts + [phase]).replace(".", "_")

    def get_name(self):
        return self.construct_phase_name(self.phase)

    def get_platform(self):
        return "macos" if self.distro.name == "macos" else "linux"

    def gen_docker_image(self):

        lang_substitutions = {
            "onnx_py2": "py2",
            "cmake": "py2",
        }

        lang = miniutils.override(self.language, lang_substitutions)
        parts = [lang] + self.get_build_name_middle_parts()
        return miniutils.quote(DOCKER_IMAGE_PATH_BASE + "-".join(parts) + ":" + str(DOCKER_IMAGE_VERSION))

    def gen_yaml_tree(self):

        tuples = []

        lang_substitutions = {
            "onnx_py2": "onnx-py2",
        }

        lang = miniutils.override(self.language, lang_substitutions)

        parts = [
            "caffe2",
            lang,
        ] + self.get_build_name_middle_parts() + [self.phase]

        build_env = "-".join(parts)
        if not self.distro.name == "macos":
            build_env = miniutils.quote(build_env)

        tuples.append(("BUILD_ENVIRONMENT", build_env))

        if self.compiler.name == "ios":
            tuples.append(("BUILD_IOS", miniutils.quote("1")))

        if self.phase == "test":
            use_cuda_docker = self.compiler.name == "cuda"
            if use_cuda_docker:
                tuples.append(("USE_CUDA_DOCKER_RUNTIME", miniutils.quote("1")))

        if not self.distro.name == "macos":
            tuples.append(("DOCKER_IMAGE", self.gen_docker_image()))

        if self.is_build_only():
            if not self.distro.name == "macos":
                tuples.append(("BUILD_ONLY", miniutils.quote("1")))

        # TODO: not sure we need the distinction between system and homebrew anymore. Our python handling in cmake
        #  and setuptools is more robust now than when we first had these.
        if self.distro.name == "macos":
            tuples.append(("PYTHON_INSTALLATION", miniutils.quote("system")))
            tuples.append(("PYTHON_VERSION", miniutils.quote("2")))

        env_dict = OrderedDict(tuples)

        d = OrderedDict([
            ("environment", env_dict),
        ])

        if self.phase == "test":
            is_large = self.compiler.name != "cuda"

            resource_class = "large" if is_large else "gpu.medium"
            d["resource_class"] = resource_class

        d["<<"] = "*" + "_".join(["caffe2", self.get_platform(), self.phase, "defaults"])

        return d


def gen_build_list():
    x = []
    for distro, d1 in CONFIG_HIERARCHY:
        for compiler_name, build_languages in d1:
            for language in build_languages:
                for phase in dimensions.PHASES:

                    c = Conf(language, distro, compiler_name, phase)

                    if phase == "build" or not c.is_build_only():
                        x.append(c)

    return x


def add_caffe2_builds(jobs_dict):

    configs = gen_build_list()
    for conf_options in configs:
        jobs_dict[conf_options.get_name()] = conf_options.gen_yaml_tree()


def get_caffe2_workflows():

    configs = gen_build_list()

    # TODO Why don't we build this config?
    # See https://github.com/pytorch/pytorch/pull/17323#discussion_r259450540
    filtered_configs = filter(lambda x: not (str(x.distro) == "ubuntu14.04" and str(x.compiler) == "gcc4.9"), configs)

    x = []
    for conf_options in filtered_configs:
        item = conf_options.get_name()

        if conf_options.phase == "test":
            item = {conf_options.get_name(): {"requires": [conf_options.construct_phase_name("build")]}}
        x.append(item)

    return x
