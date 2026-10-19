"""Load dependency-free upstream modules without executing its eager package init.

This is an explicitly scoped offline runner, not a replacement implementation of
LegalKit's GPU/multiprocessing command line. Upstream source remains unchanged.
"""
import importlib.util
import os
import sys
from pathlib import Path


def toolkit_root():
    explicit = os.getenv("LEGALKIT_ROOT")
    if explicit:
        return Path(explicit).resolve()
    candidates = [Path(__file__).resolve().parents[1] / "third_party/LegalKit"]
    candidates.extend(parent / "third_party/LegalKit" for parent in (Path.cwd(), *Path.cwd().parents))
    for candidate in candidates:
        if (candidate / "legalkit/datasets/base.py").is_file():
            return candidate.resolve()
    # Installed wheels can also locate a separately editable-installed LegalKit.
    spec = importlib.util.find_spec("legalkit")
    if spec and spec.origin:
        return Path(spec.origin).resolve().parents[1]
    return candidates[0].resolve()


def load_upstream(relative_path, name):
    path = toolkit_root() / relative_path
    if not path.is_file():
        raise ValueError(f"缺少 LegalKit 源文件 {path}；请按 docs/LEGALKIT.md 拉取源码")
    module_key = "_cail_legalkit_" + name
    existing = sys.modules.get(module_key)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise ValueError("本进程内不能切换 LegalKit 源码根目录")
        return existing
    spec = importlib.util.spec_from_file_location(module_key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_key, None)
        raise
    return module
