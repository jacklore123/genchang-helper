#!/usr/bin/env python3
"""项目内公用路径。所有脚本都从这里取路径，保证在任何机器上一致。"""
import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
APP = os.path.join(ROOT, "app")
UI = os.path.join(APP, "ui")
ENGINE = os.path.join(APP, "engine")
MODELS = os.path.join(APP, "models")
ANDROID = os.path.join(ROOT, "android")
LIBRARY = os.environ.get("GENCHANG_LIB") or os.path.join(ROOT, "library")
SONGS = os.path.join(ROOT, "songs")
DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(ROOT, "发布")
BUILD = os.path.join(ROOT, ".build")

MODEL_FILE = "UVR-MDX-NET-Inst_HQ_3.onnx"

# UVR 官方模型仓库（GitHub 直连不通时可用镜像前缀）
MODEL_BASE = os.environ.get("GENCHANG_MODEL_BASE",
                            "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/")
MODEL_MIRRORS = [
    "",
    "https://ghfast.top/",
    "https://gh-proxy.com/",
]


def model_path():
    p = os.path.join(MODELS, MODEL_FILE)
    return p if os.path.isfile(p) else None
