from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config

SKIP_SCAN_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "public",
    "site",
    "www",
    "web",
    "data",
    "target",
    "vendor",
    "dist",
    "build",
    ".pip",
    ".gradle",
}

# 拡張子 → ランタイム ID（制限なし。未知の言語もここに足せる）
EXT_TO_RUNTIME: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".jsx": "node",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".vb": "vbnet",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".r": "r",
    ".dart": "dart",
    ".exs": "elixir",
    ".ex": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".scala": "scala",
    ".groovy": "groovy",
    ".clj": "clojure",
    ".nim": "nim",
    ".cr": "crystal",
    ".zig": "zig",
    ".v": "vlang",
    ".d": "d",
    ".ml": "ocaml",
    ".swift": "swift",
    ".jl": "julia",
    ".lisp": "lisp",
    ".rkt": "racket",
    ".scm": "scheme",
    ".pas": "pascal",
    ".pp": "pascal",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f": "fortran",
    ".for": "fortran",
    ".cob": "cobol",
    ".cbl": "cobol",
    ".s": "asm",
    ".asm": "asm",
    ".coffee": "coffeescript",
    ".m": "objc",
}

ENTRY_CANDIDATES = (
    "bot.py",
    "main.py",
    "index.py",
    "app.py",
    "bot.js",
    "index.js",
    "main.js",
    "app.js",
    "bot.ts",
    "index.ts",
    "main.ts",
    "app.ts",
    "bot.mjs",
    "main.go",
    "bot.go",
    "src/main.rs",
    "bot.rb",
    "main.rb",
    "index.php",
    "bot.php",
    "bot.lua",
    "main.lua",
    "bot.pl",
    "main.pl",
    "Main.java",
    "Bot.java",
    "Main.kt",
    "Program.cs",
    "main.c",
    "main.cpp",
    "bot.sh",
    "main.sh",
    "start.sh",
    "bot.ps1",
    "main.ps1",
    "main.dart",
    "main.r",
    "main.R",
    "main.jl",
    "main.nim",
    "main.zig",
    "main.cr",
    "main.exs",
    "Main.hs",
    "main.swift",
)

SHEBANG_RUNTIME = {
    "python": "python",
    "python3": "python",
    "python2": "python",
    "pypy": "python",
    "pypy3": "python",
    "node": "node",
    "nodejs": "node",
    "deno": "deno",
    "bun": "bun",
    "ruby": "ruby",
    "perl": "perl",
    "php": "php",
    "lua": "lua",
    "lua5.4": "lua",
    "lua5.3": "lua",
    "bash": "bash",
    "sh": "bash",
    "zsh": "bash",
    "pwsh": "powershell",
    "powershell": "powershell",
    "dotnet": "csharp",
    "java": "java",
    "dart": "dart",
    "rscript": "r",
    "elixir": "elixir",
    "crystal": "crystal",
    "nim": "nim",
    "julia": "julia",
    "racket": "racket",
    "sbcl": "lisp",
}


@dataclass(frozen=True)
class PkgSpec:
    """未インストール時に入れるパッケージ名（各パッケージマネージャ）。"""

    binaries: tuple[str, ...]
    termux: tuple[str, ...] = ()
    apt: tuple[str, ...] = ()
    pacman: tuple[str, ...] = ()
    dnf: tuple[str, ...] = ()
    apk: tuple[str, ...] = ()
    brew: tuple[str, ...] = ()
    winget: tuple[str, ...] = ()


# ランタイムごとに「どのコマンドがあれば動くか」と「無ければ何を入れるか」
PKG: dict[str, PkgSpec] = {
    "python": PkgSpec(("python3", "python"), ("python",), ("python3", "python3-pip"), ("python",), ("python3",), ("python3", "py3-pip"), ("python",), ("Python.Python.3.12",)),
    "node": PkgSpec(("node",), ("nodejs",), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("node",), ("OpenJS.NodeJS",)),
    "typescript": PkgSpec(("node",), ("nodejs",), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("node",), ("OpenJS.NodeJS",)),
    "deno": PkgSpec(("deno",), ("deno",), ("deno",), ("deno",), ("deno",), ("deno",), ("deno",), ("DenoLand.Deno",)),
    "bun": PkgSpec(("bun",), ("bun",), (), (), (), (), ("oven-sh/bun/bun",), ("Oven-sh.Bun",)),
    "go": PkgSpec(("go",), ("golang",), ("golang-go",), ("go",), ("golang",), ("go",), ("go",), ("GoLang.Go",)),
    "rust": PkgSpec(("cargo", "rustc"), ("rust",), ("cargo", "rustc"), ("rust",), ("cargo", "rust"), ("cargo", "rust"), ("rust",), ("Rustlang.Rust.MSVC",)),
    "ruby": PkgSpec(("ruby",), ("ruby",), ("ruby", "ruby-bundler"), ("ruby",), ("ruby", "rubygem-bundler"), ("ruby",), ("ruby",), ("RubyInstallerTeam.Ruby.3.2",)),
    "php": PkgSpec(("php",), ("php",), ("php-cli", "composer"), ("php", "composer"), ("php", "composer"), ("php", "composer"), ("php",), ("PHP.PHP.8.3",)),
    "lua": PkgSpec(("lua", "lua5.4", "lua5.3"), ("lua54",), ("lua5.4",), ("lua",), ("lua",), ("lua5.4",), ("lua",), ()),
    "perl": PkgSpec(("perl",), ("perl",), ("perl",), ("perl",), ("perl",), ("perl",), ("perl",), ("StrawberryPerl.StrawberryPerl",)),
    "java": PkgSpec(("java", "javac"), ("openjdk-17",), ("default-jdk",), ("jdk-openjdk",), ("java-17-openjdk-devel",), ("openjdk17",), ("openjdk",), ("Microsoft.OpenJDK.17",)),
    "kotlin": PkgSpec(("kotlinc", "kotlin"), ("kotlin",), ("kotlin",), ("kotlin",), (), (), ("kotlin",), ()),
    "csharp": PkgSpec(("dotnet",), ("dotnet",), ("dotnet-sdk-8.0",), ("dotnet-sdk",), ("dotnet-sdk-8.0",), (), ("dotnet",), ("Microsoft.DotNet.SDK.8",)),
    "fsharp": PkgSpec(("dotnet",), ("dotnet",), ("dotnet-sdk-8.0",), ("dotnet-sdk",), ("dotnet-sdk-8.0",), (), ("dotnet",), ("Microsoft.DotNet.SDK.8",)),
    "vbnet": PkgSpec(("dotnet",), ("dotnet",), ("dotnet-sdk-8.0",), ("dotnet-sdk",), ("dotnet-sdk-8.0",), (), ("dotnet",), ("Microsoft.DotNet.SDK.8",)),
    "c": PkgSpec(("cc", "gcc", "clang"), ("clang",), ("gcc",), ("gcc",), ("gcc",), ("gcc",), ("gcc",), ()),
    "cpp": PkgSpec(("c++", "g++", "clang++"), ("clang",), ("g++",), ("gcc",), ("gcc-c++",), ("g++",), ("gcc",), ()),
    "bash": PkgSpec(("bash", "sh"), ("bash",), ("bash",), ("bash",), ("bash",), ("bash",), ("bash",), ()),
    "powershell": PkgSpec(("pwsh", "powershell"), (), ("powershell",), (), ("powershell",), (), ("powershell",), ("Microsoft.PowerShell",)),
    "r": PkgSpec(("Rscript", "R"), ("r-base",), ("r-base",), ("r",), ("R",), ("R",), ("r",), ("RProject.R",)),
    "dart": PkgSpec(("dart",), ("dart",), ("dart",), ("dart",), (), (), ("dart",), ("Google.DartSDK",)),
    "elixir": PkgSpec(("elixir",), ("elixir",), ("elixir",), ("elixir",), ("elixir",), ("elixir",), ("elixir",), ()),
    "erlang": PkgSpec(("escript", "erl"), ("erlang",), ("erlang",), ("erlang",), ("erlang",), ("erlang",), ("erlang",), ()),
    "haskell": PkgSpec(("runghc", "ghc"), ("ghc",), ("ghc",), ("ghc",), ("ghc",), ("ghc",), ("ghc",), ()),
    "scala": PkgSpec(("scala", "scalac"), ("scala",), ("scala",), ("scala",), (), (), ("scala",), ()),
    "groovy": PkgSpec(("groovy",), ("groovy",), ("groovy",), ("groovy",), (), (), ("groovy",), ()),
    "clojure": PkgSpec(("clojure",), ("clojure",), ("clojure",), ("clojure",), (), (), ("clojure",), ()),
    "nim": PkgSpec(("nim",), ("nim",), ("nim",), ("nim",), ("nim",), ("nim",), ("nim",), ()),
    "crystal": PkgSpec(("crystal",), ("crystal",), ("crystal",), ("crystal",), (), ("crystal",), ("crystal",), ()),
    "zig": PkgSpec(("zig",), ("zig",), ("zig",), ("zig",), ("zig",), ("zig",), ("zig",), ("zig.zig",)),
    "vlang": PkgSpec(("v",), ("vlang",), (), ("vlang",), (), (), ("vlang",), ()),
    "d": PkgSpec(("dmd", "ldc2", "gdc"), ("dmd",), ("gdc",), ("dmd",), ("gcc-gdc",), ("gdc",), ("dmd",), ()),
    "ocaml": PkgSpec(("ocaml",), ("ocaml",), ("ocaml",), ("ocaml",), ("ocaml",), ("ocaml",), ("ocaml",), ()),
    "swift": PkgSpec(("swift",), (), (), (), (), (), ("swift",), ()),
    "julia": PkgSpec(("julia",), ("julia",), ("julia",), ("julia",), ("julia",), ("julia",), ("julia",), ("Julialang.Julia",)),
    "lisp": PkgSpec(("sbcl",), ("sbcl",), ("sbcl",), ("sbcl",), ("sbcl",), ("sbcl",), ("sbcl",), ()),
    "racket": PkgSpec(("racket",), ("racket",), ("racket",), ("racket",), (), ("racket",), ("racket",), ()),
    "scheme": PkgSpec(("guile", "csi", "gosh"), ("guile",), ("guile",), ("guile",), ("guile",), ("guile",), ("guile",), ()),
    "pascal": PkgSpec(("fpc",), ("fpc",), ("fp-compiler",), ("fpc",), ("fpc",), ("fpc",), ("fpc",), ()),
    "fortran": PkgSpec(("gfortran",), ("gfortran",), ("gfortran",), ("gcc-fortran",), ("gcc-gfortran",), ("gfortran",), ("gcc",), ()),
    "cobol": PkgSpec(("cobc",), ("gnucobol",), ("gnucobol",), ("gnucobol",), (), (), (), ()),
    "asm": PkgSpec(("nasm", "as"), ("nasm",), ("nasm",), ("nasm",), ("nasm",), ("nasm",), ("nasm",), ()),
    "objc": PkgSpec(("clang", "gcc"), ("clang",), ("gobjc",), ("gcc",), ("gcc",), ("gcc",), ("gcc",), ()),
    "coffeescript": PkgSpec(("node",), ("nodejs",), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("nodejs", "npm"), ("node",), ("OpenJS.NodeJS",)),
}

ALIASES = {
    "js": "node",
    "javascript": "node",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "golang": "go",
    "rs": "rust",
    "c++": "cpp",
    "cxx": "cpp",
    "cs": "csharp",
    "dotnet": "csharp",
    "pwsh": "powershell",
    "shell": "bash",
    "sh": "bash",
    "kt": "kotlin",
}

_install_lock = asyncio.Lock()


def is_termux() -> bool:
    if os.environ.get("TERMUX_VERSION"):
        return True
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix:
        return True
    return Path("/data/data/com.termux/files/usr").exists()


def extra_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    prefix = os.environ.get("PREFIX")
    if prefix:
        dirs.append(Path(prefix) / "bin")
    home = Path.home()
    dirs.extend(
        [
            home / ".cargo" / "bin",
            home / "go" / "bin",
            home / ".deno" / "bin",
            home / ".bun" / "bin",
            home / ".local" / "bin",
            home / ".dotnet",
        ]
    )
    if is_termux():
        dirs.append(Path("/data/data/com.termux/files/usr/bin"))
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        dirs.extend(
            [
                local / "Programs" / "Python",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Go" / "bin",
                Path(os.environ.get("USERPROFILE", str(home))) / ".cargo" / "bin",
            ]
        )
    return [d for d in dirs if d]


def which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        for ext in (".cmd", ".bat", ".exe", ".ps1"):
            found = shutil.which(name + ext)
            if found:
                return found
    for folder in extra_bin_dirs():
        candidate = folder / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        if sys.platform == "win32":
            for ext in (".exe", ".cmd", ".bat"):
                win = folder / f"{name}{ext}"
                if win.is_file():
                    return str(win)
    return None


def which_any(*names: str) -> str | None:
    for name in names:
        found = which(name)
        if found:
            return found
    return None


def process_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {**os.environ, **(extra or {})}
    parts = [str(p) for p in extra_bin_dirs() if p.exists()]
    current = env.get("PATH") or env.get("Path") or ""
    sep = ";" if sys.platform == "win32" else ":"
    env["PATH"] = sep.join(parts + ([current] if current else []))
    env["Path"] = env["PATH"]
    return env


def normalize_runtime(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower().lstrip(".")
    return ALIASES.get(key, key)


def read_shebang(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            head = f.readline(200)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    text = head.decode("utf-8", errors="replace").strip()[2:].strip()
    parts = text.replace("\\", "/").split()
    if not parts:
        return None
    cmd = parts[-1] if parts[0].endswith("/env") and len(parts) > 1 else parts[0]
    cmd = Path(cmd).name.lower()
    return SHEBANG_RUNTIME.get(cmd, cmd if cmd in PKG else None)


def _load_cloud_meta(directory: Path) -> dict:
    for name in ("soucloud.json", "cloud.json"):
        path = directory / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def _package_json_start(directory: Path) -> bool:
    path = directory / "package.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    scripts = data.get("scripts") or {}
    return bool(scripts.get("start"))


def detect(directory: Path, preferred_entry: str | None = None, hint: str | None = None) -> tuple[str, str]:
    """ディレクトリから (runtime, entry) を推定する。"""
    meta = _load_cloud_meta(directory)
    hint = normalize_runtime(hint or meta.get("runtime") or meta.get("language"))
    if preferred_entry:
        preferred_entry = preferred_entry.replace("\\", "/")
    if meta.get("entry"):
        preferred_entry = preferred_entry or str(meta["entry"])

    if preferred_entry and (directory / preferred_entry).exists():
        runtime = hint or _runtime_from_file(directory / preferred_entry) or "generic"
        return runtime, preferred_entry

    manifests = [
        ("package.json", "node", "index.js"),
        ("tsconfig.json", "typescript", "index.ts"),
        ("Cargo.toml", "rust", "src/main.rs"),
        ("go.mod", "go", "main.go"),
        ("composer.json", "php", "index.php"),
        ("Gemfile", "ruby", "main.rb"),
        ("pyproject.toml", "python", "bot.py"),
        ("requirements.txt", "python", "bot.py"),
        ("pom.xml", "java", "Main.java"),
        ("build.gradle", "java", "Main.java"),
        ("build.gradle.kts", "kotlin", "Main.kt"),
        ("mix.exs", "elixir", "mix.exs"),
        (".csproj", "csharp", None),
    ]
    for filename, runtime, default_entry in manifests:
        if filename.startswith("."):
            matches = list(directory.glob(f"*{filename}"))
            if matches:
                entry = preferred_entry or matches[0].name
                return hint or runtime, entry
        elif (directory / filename).exists():
            entry = preferred_entry
            if not entry:
                if runtime == "node" and _package_json_start(directory):
                    entry = "package.json"
                else:
                    entry = default_entry or filename
                    if not (directory / entry).exists():
                        found = _first_source(directory, runtime)
                        entry = found or filename
            return hint or runtime, entry

    for name in ENTRY_CANDIDATES:
        if (directory / name).exists():
            runtime = hint or _runtime_from_file(directory / name) or "generic"
            return runtime, name

    source = _first_source(directory, hint)
    if source:
        runtime = hint or _runtime_from_file(directory / source) or "generic"
        return runtime, source

    return hint or "python", preferred_entry or "bot.py"


def _runtime_from_file(path: Path) -> str | None:
    shebang = read_shebang(path)
    if shebang:
        return shebang
    return EXT_TO_RUNTIME.get(path.suffix.lower())


def _first_source(directory: Path, runtime: str | None = None) -> str | None:
    wanted_exts: set[str] = set()
    if runtime:
        wanted_exts = {ext for ext, rid in EXT_TO_RUNTIME.items() if rid == runtime}
    found_any: str | None = None
    for item in sorted(directory.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(directory).as_posix()
        parts = set(Path(rel).parts)
        if parts & SKIP_SCAN_DIRS:
            continue
        if item.name.startswith("."):
            continue
        ext = item.suffix.lower()
        if wanted_exts and ext in wanted_exts:
            return rel
        if ext in EXT_TO_RUNTIME and found_any is None:
            found_any = rel
    return found_any


def resolve_entry(directory: Path, preferred: str | None = None, hint: str | None = None) -> tuple[str, str]:
    runtime, entry = detect(directory, preferred, hint)
    if preferred and (directory / preferred).exists():
        return runtime, preferred
    return runtime, entry


def _pkg_names(spec: PkgSpec) -> tuple[str, list[str]]:
    if is_termux() and which("pkg"):
        return "termux", list(spec.termux)
    if sys.platform == "win32" and which("winget"):
        return "winget", list(spec.winget)
    if which("apt-get"):
        return "apt", list(spec.apt)
    if which("pacman"):
        return "pacman", list(spec.pacman)
    if which("dnf"):
        return "dnf", list(spec.dnf)
    if which("apk"):
        return "apk", list(spec.apk)
    if which("brew"):
        return "brew", list(spec.brew)
    if which("pkg") and is_termux():
        return "termux", list(spec.termux)
    return "", []


def _install_argv(manager: str, packages: list[str]) -> list[list[str]]:
    if not packages:
        return []
    if manager == "termux":
        return [["pkg", "install", "-y", *packages]]
    if manager == "apt":
        cmds = [["apt-get", "update", "-y"], ["apt-get", "install", "-y", *packages]]
        need_sudo = hasattr(os, "geteuid") and os.geteuid() != 0
        if need_sudo and which("sudo"):
            cmds = [[which("sudo") or "sudo", "-n", *c] for c in cmds]
        return cmds
    if manager == "pacman":
        return [["pacman", "-Sy", "--noconfirm", *packages]]
    if manager == "dnf":
        return [["dnf", "install", "-y", *packages]]
    if manager == "apk":
        return [["apk", "add", *packages]]
    if manager == "brew":
        return [["brew", "install", *packages]]
    if manager == "winget":
        return [
            [
                "winget",
                "install",
                "-e",
                "--id",
                pkg,
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
            for pkg in packages
        ]
    return []


async def run_cmd(args: list[str], cwd: Path | None = None, timeout: int | None = None) -> str:
    timeout = timeout or config.INSTALL_TIMEOUT_SEC
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=process_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("コマンドがタイムアウトしました") from None
    out = (stdout or b"").decode("utf-8", errors="replace") + (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(out[-2000:] or f"exit {proc.returncode}")
    return out


async def ensure_runtime(runtime: str, log=None) -> None:
    runtime = normalize_runtime(runtime) or runtime
    if runtime in ("python", None):
        return
    if runtime == "generic":
        return
    spec = PKG.get(runtime)
    if not spec:
        return
    if which_any(*spec.binaries):
        return
    manager, packages = _pkg_names(spec)
    if not packages:
        raise RuntimeError(
            f"ランタイム `{runtime}` が見つかりません。この環境では自動インストール用のパッケージが未対応です。"
            f" `{spec.binaries[0]}` を手動インストールしてください。"
        )
    if log:
        log(f"ランタイム `{runtime}` が見つからないため自動インストールします（{manager}: {' '.join(packages)}）")
    async with _install_lock:
        if which_any(*spec.binaries):
            return
        last_err = None
        for argv in _install_argv(manager, packages):
            try:
                await run_cmd(argv, timeout=config.RUNTIME_INSTALL_TIMEOUT_SEC)
            except RuntimeError as err:
                last_err = err
        if not which_any(*spec.binaries):
            raise RuntimeError(
                f"`{runtime}` の自動インストールに失敗しました。"
                + (f"\n{last_err}" if last_err else "")
            )
    if log:
        log(f"ランタイム `{runtime}` のインストール完了")


def _npm() -> str:
    return which_any("npm", "npm.cmd") or "npm"


def _npx() -> str:
    return which_any("npx", "npx.cmd") or "npx"


def _lua() -> str:
    return which_any("lua", "lua5.4", "lua5.3", "lua54") or "lua"


def _python() -> str:
    return sys.executable


def start_argv(directory: Path, runtime: str, entry: str) -> list[str]:
    runtime = normalize_runtime(runtime) or runtime
    entry_path = directory / entry

    if runtime == "python":
        return [_python(), entry]
    if runtime in ("node", "javascript"):
        if entry == "package.json" or _package_json_start(directory):
            return [_npm(), "start"]
        return [which_any("node") or "node", entry]
    if runtime == "typescript":
        if _package_json_start(directory):
            return [_npm(), "start"]
        return [_npx(), "--yes", "tsx", entry]
    if runtime == "deno":
        return [which_any("deno") or "deno", "run", "-A", entry]
    if runtime == "bun":
        return [which_any("bun") or "bun", "run", entry]
    if runtime == "go":
        if (directory / "go.mod").exists():
            return [which_any("go") or "go", "run", "."]
        return [which_any("go") or "go", "run", entry]
    if runtime == "rust":
        if (directory / "Cargo.toml").exists():
            return [which_any("cargo") or "cargo", "run", "--release"]
        rustc = which_any("rustc") or "rustc"
        return [rustc, "-O", "-o", ".soucloud_run", entry]
    if runtime == "ruby":
        if (directory / "Gemfile").exists() and which("bundle"):
            return [which("bundle") or "bundle", "exec", "ruby", entry]
        return [which_any("ruby") or "ruby", entry]
    if runtime == "php":
        return [which_any("php") or "php", entry]
    if runtime == "lua":
        return [_lua(), entry]
    if runtime == "perl":
        return [which_any("perl") or "perl", entry]
    if runtime == "java":
        return [which_any("java") or "java", "-cp", ".", Path(entry).stem]
    if runtime == "kotlin":
        jar = ".soucloud_run.jar"
        return [which_any("kotlin") or "java", "-jar", jar]
    if runtime in ("csharp", "fsharp", "vbnet"):
        return [which_any("dotnet") or "dotnet", "run"]
    if runtime == "c":
        return [str(directory / ".soucloud_run")]
    if runtime == "cpp":
        return [str(directory / ".soucloud_run")]
    if runtime == "bash":
        return [which_any("bash", "sh") or "bash", entry]
    if runtime == "powershell":
        return [which_any("pwsh", "powershell") or "pwsh", "-File", entry]
    if runtime == "r":
        return [which_any("Rscript") or "Rscript", entry]
    if runtime == "dart":
        return [which_any("dart") or "dart", "run", entry]
    if runtime == "elixir":
        if (directory / "mix.exs").exists():
            return [which_any("mix") or "mix", "run", "--no-halt"]
        return [which_any("elixir") or "elixir", entry]
    if runtime == "erlang":
        return [which_any("escript") or "escript", entry]
    if runtime == "haskell":
        return [which_any("runghc") or "runghc", entry]
    if runtime == "scala":
        return [which_any("scala") or "scala", entry]
    if runtime == "groovy":
        return [which_any("groovy") or "groovy", entry]
    if runtime == "clojure":
        return [which_any("clojure") or "clojure", "-M", entry]
    if runtime == "nim":
        return [which_any("nim") or "nim", "c", "-r", entry]
    if runtime == "crystal":
        return [which_any("crystal") or "crystal", "run", entry]
    if runtime == "zig":
        return [which_any("zig") or "zig", "run", entry]
    if runtime == "vlang":
        return [which_any("v") or "v", "run", entry]
    if runtime == "d":
        return [which_any("dmd", "ldc2", "gdc") or "dmd", "-run", entry]
    if runtime == "ocaml":
        return [which_any("ocaml") or "ocaml", entry]
    if runtime == "swift":
        return [which_any("swift") or "swift", entry]
    if runtime == "julia":
        return [which_any("julia") or "julia", entry]
    if runtime == "lisp":
        return [which_any("sbcl") or "sbcl", "--script", entry]
    if runtime == "racket":
        return [which_any("racket") or "racket", entry]
    if runtime == "scheme":
        return [which_any("guile", "csi", "gosh") or "guile", entry]
    if runtime == "pascal":
        return [str(directory / ".soucloud_run")]
    if runtime == "fortran":
        return [str(directory / ".soucloud_run")]
    if runtime == "cobol":
        return [str(directory / ".soucloud_run")]
    if runtime == "asm":
        return [str(directory / ".soucloud_run")]
    if runtime == "coffeescript":
        return [_npx(), "--yes", "coffee", entry]
    if runtime == "objc":
        return [str(directory / ".soucloud_run")]

    shebang = read_shebang(entry_path) if entry_path.exists() else None
    if shebang:
        interp = which_any(*PKG.get(shebang, PkgSpec((shebang,))).binaries) or shebang
        return [interp, entry]
    if sys.platform != "win32" and entry_path.exists():
        return [str(entry_path)]
    raise RuntimeError(f"エントリ `{entry}` の実行方法が分かりません（runtime={runtime}）")


async def prepare_build(directory: Path, runtime: str, entry: str, log=None) -> list[str]:
    """コンパイルが必要な言語は起動前にビルドし、実行 argv を返す。"""
    runtime = normalize_runtime(runtime) or runtime
    out = directory / ".soucloud_run"
    if runtime == "rust" and not (directory / "Cargo.toml").exists():
        rustc = which_any("rustc") or "rustc"
        if log:
            log("rustc でビルド中...")
        await run_cmd([rustc, "-O", "-o", str(out), entry], directory)
        return [str(out)]
    if runtime == "java":
        javac = which_any("javac") or "javac"
        if log:
            log("javac でコンパイル中...")
        await run_cmd([javac, entry], directory)
        return [which_any("java") or "java", "-cp", ".", Path(entry).stem]
    if runtime == "kotlin":
        kotlinc = which_any("kotlinc") or "kotlinc"
        jar = directory / ".soucloud_run.jar"
        if log:
            log("kotlinc でコンパイル中...")
        await run_cmd([kotlinc, entry, "-include-runtime", "-d", str(jar)], directory)
        java = which_any("java") or "java"
        return [java, "-jar", str(jar)]
    if runtime == "c":
        cc = which_any("cc", "gcc", "clang") or "cc"
        if log:
            log("C をコンパイル中...")
        await run_cmd([cc, "-O2", "-o", str(out), entry], directory)
        return [str(out)]
    if runtime == "cpp":
        cxx = which_any("c++", "g++", "clang++") or "c++"
        if log:
            log("C++ をコンパイル中...")
        await run_cmd([cxx, "-O2", "-o", str(out), entry], directory)
        return [str(out)]
    if runtime == "pascal":
        fpc = which_any("fpc") or "fpc"
        await run_cmd([fpc, "-o" + str(out), entry], directory)
        return [str(out)]
    if runtime == "fortran":
        gfortran = which_any("gfortran") or "gfortran"
        await run_cmd([gfortran, "-O2", "-o", str(out), entry], directory)
        return [str(out)]
    if runtime == "cobol":
        cobc = which_any("cobc") or "cobc"
        await run_cmd([cobc, "-x", "-o", str(out), entry], directory)
        return [str(out)]
    if runtime == "asm":
        nasm = which_any("nasm")
        if nasm and sys.platform != "win32":
            obj = directory / ".soucloud_run.o"
            await run_cmd([nasm, "-felf64", entry, "-o", str(obj)], directory)
            ld = which_any("ld") or "ld"
            await run_cmd([ld, str(obj), "-o", str(out)], directory)
            return [str(out)]
    if runtime == "objc":
        clang = which_any("clang", "gcc") or "clang"
        await run_cmd([clang, "-O2", "-o", str(out), entry, "-lobjc"], directory)
        return [str(out)]
    argv = start_argv(directory, runtime, entry)
    if runtime in ("c", "cpp") or (argv and argv[0] == str(out)):
        return argv
    return argv


async def install_dependencies(directory: Path, runtime: str, log=None) -> None:
    runtime = normalize_runtime(runtime) or "python"
    try:
        if (directory / "requirements.txt").exists() or runtime == "python" and (directory / "pyproject.toml").exists():
            if (directory / "requirements.txt").exists():
                if log:
                    log("pip で依存関係をインストール中...")
                target = directory / ".pip"
                await run_cmd(
                    [_python(), "-m", "pip", "install", "-r", "requirements.txt", "-t", str(target)],
                    directory,
                )
        if (directory / "package.json").exists():
            if log:
                log("npm install 中...")
            await run_cmd([_npm(), "install"], directory)
        if (directory / "Cargo.toml").exists():
            if log:
                log("cargo fetch 中...")
            await run_cmd([which_any("cargo") or "cargo", "fetch"], directory)
        if (directory / "go.mod").exists():
            if log:
                log("go mod download 中...")
            await run_cmd([which_any("go") or "go", "mod", "download"], directory)
        if (directory / "composer.json").exists() and which("composer"):
            if log:
                log("composer install 中...")
            await run_cmd([which("composer") or "composer", "install", "--no-interaction"], directory)
        if (directory / "Gemfile").exists() and which("bundle"):
            if log:
                log("bundle install 中...")
            await run_cmd([which("bundle") or "bundle", "install"], directory)
        if (directory / "mix.exs").exists() and which("mix"):
            if log:
                log("mix deps.get 中...")
            await run_cmd([which("mix") or "mix", "deps.get"], directory)
    except RuntimeError as err:
        if log:
            log(f"依存関係のインストール警告: {err}")


def language_choices(current: str = "") -> list[str]:
    names = sorted(set(PKG) | set(ALIASES) | {"generic"})
    current = current.lower()
    if current:
        names = [n for n in names if current in n]
    return names[:25]


def allowed_source_suffix(filename: str) -> bool:
    lower = filename.lower()
    if lower.endswith(".zip"):
        return True
    ext = Path(lower).suffix
    return ext in EXT_TO_RUNTIME or ext in {".json", ".toml", ".gradle", ".mod"}
