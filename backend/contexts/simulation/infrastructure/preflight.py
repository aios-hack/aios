from __future__ import annotations

import enum
import json
import shutil
import subprocess
from dataclasses import dataclass
from subprocess import run as _subprocess_run

from backend.contexts.runs.infrastructure.provenance import opm_image

__all__ = [
    "DOCKER_PROBE_TIMEOUT_SECONDS",
    "DockerPreflightError",
    "ImageReference",
    "PreflightProblem",
    "PreflightReport",
    "ensure_docker_ready",
    "docker_preflight",
    "run_docker",
    "docker_unavailable_reason",
    "resolve_image_reference",
]

DOCKER_PROBE_TIMEOUT_SECONDS = 15.0

_PERMISSION_MARKERS: tuple[str, ...] = (
    "permission denied",
    "got permission denied",
    "dial unix /var/run/docker.sock: connect: permission denied",
    "access is denied",
    "requested resource is unavailable",
    "error during connect",
    "не удалось получить доступ",
)

_DAEMON_MARKERS: tuple[str, ...] = (
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "the docker daemon is not running",
    "docker daemon is not running",
    "connection refused",
    "no such file or directory",
    "system cannot find the file specified",
    "pipe/dockerdesktoplinuxengine",
)


class PreflightProblem(enum.Enum):
    OK = "ok"
    BINARY_MISSING = "binary-missing"
    DAEMON_DOWN = "daemon-down"
    PERMISSION_DENIED = "permission-denied"
    IMAGE_MISSING = "image-missing"


class DockerPreflightError(RuntimeError):

    def __init__(self, report: "PreflightReport") -> None:
        super().__init__(report.message)
        self.report = report
        self.problem = report.problem


@dataclass(frozen=True, slots=True)
class ImageReference:
    image: str
    digest: str | None
    pinned: bool


@dataclass(frozen=True, slots=True)
class PreflightReport:
    problem: PreflightProblem
    image: str
    message: str
    detail: str
    digest: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is PreflightProblem.OK


_MESSAGES: dict[PreflightProblem, str] = {
    PreflightProblem.BINARY_MISSING: (
        "не удалось запустить {binary!r}: исполняемый файл Docker отсутствует "
        "в PATH. Установите Docker и убедитесь, что клиент доступен из этой оболочки."
    ),
    PreflightProblem.DAEMON_DOWN: (
        "Демон Docker не отвечает: {detail}. "
        "Запустите Docker Desktop или службу docker и повторите."
    ),
    PreflightProblem.PERMISSION_DENIED: (
        "Нет прав на обращение к Docker: {detail}. "
        "Добавьте пользователя в группу docker (или запустите с нужными правами) "
        "и заново войдите в сессию."
    ),
    PreflightProblem.IMAGE_MISSING: (
        "Образ OPM {image!r} не найден локально: {detail}. "
        "Загрузите его командой docker pull {image}."
    ),
}


def _classify_daemon_failure(text: str) -> PreflightProblem:
    lowered = text.lower()
    for marker in _PERMISSION_MARKERS:
        if marker in lowered:
            return PreflightProblem.PERMISSION_DENIED
    for marker in _DAEMON_MARKERS:
        if marker in lowered:
            return PreflightProblem.DAEMON_DOWN
    return PreflightProblem.DAEMON_DOWN


def _tail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "нет ответа от демона"
    return lines[-1]


def run_docker(
    command: list[str], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    return _subprocess_run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
    )


def _probe(
    command: list[str], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str] | None:
    try:
        return run_docker(command, timeout_seconds=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _repo_digest(payload: str, image: str) -> str | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        if not parsed:
            return None
        entry = parsed[0]
    else:
        entry = parsed
    if not isinstance(entry, dict):
        return None
    digests = entry.get("RepoDigests")
    if not isinstance(digests, list):
        return None
    candidates = [item for item in digests if isinstance(item, str) and "@sha256:" in item]
    if not candidates:
        return None
    repository = image.split("@", 1)[0].rsplit(":", 1)[0]
    for candidate in candidates:
        if candidate.split("@", 1)[0] == repository:
            return candidate
    return candidates[0]


def docker_preflight(
    *,
    image: str | None = None,
    docker_binary: str = "docker",
    timeout_seconds: float = DOCKER_PROBE_TIMEOUT_SECONDS,
    require_image: bool = True,
) -> PreflightReport:
    target = image or opm_image()
    binary = shutil.which(docker_binary) or docker_binary
    if shutil.which(docker_binary) is None:
        return PreflightReport(
            problem=PreflightProblem.BINARY_MISSING,
            image=target,
            message=_MESSAGES[PreflightProblem.BINARY_MISSING].format(
                binary=docker_binary
            ),
            detail=f"{docker_binary} not found in PATH",
        )

    info = _probe(
        [binary, "info", "--format", "{{.ServerVersion}}"],
        timeout_seconds=timeout_seconds,
    )
    if info is None:
        detail = f"клиент не ответил за {timeout_seconds:g} с"
        return PreflightReport(
            problem=PreflightProblem.DAEMON_DOWN,
            image=target,
            message=_MESSAGES[PreflightProblem.DAEMON_DOWN].format(detail=detail),
            detail=detail,
        )
    if info.returncode != 0:
        raw = info.stderr.strip() or info.stdout.strip()
        detail = _tail(raw)
        problem = _classify_daemon_failure(raw)
        return PreflightReport(
            problem=problem,
            image=target,
            message=_MESSAGES[problem].format(detail=detail),
            detail=detail,
        )

    if not require_image:
        return PreflightReport(
            problem=PreflightProblem.OK,
            image=target,
            message=f"Docker готов, образ {target} не проверялся",
            detail=info.stdout.strip(),
        )

    inspect = _probe(
        [binary, "image", "inspect", target, "--format", "{{json .}}"],
        timeout_seconds=timeout_seconds,
    )
    if inspect is None:
        detail = f"docker image inspect не ответил за {timeout_seconds:g} с"
        return PreflightReport(
            problem=PreflightProblem.IMAGE_MISSING,
            image=target,
            message=_MESSAGES[PreflightProblem.IMAGE_MISSING].format(
                image=target, detail=detail
            ),
            detail=detail,
        )
    if inspect.returncode != 0:
        raw = inspect.stderr.strip() or inspect.stdout.strip()
        detail = _tail(raw)
        lowered = raw.lower()
        if any(marker in lowered for marker in _PERMISSION_MARKERS):
            return PreflightReport(
                problem=PreflightProblem.PERMISSION_DENIED,
                image=target,
                message=_MESSAGES[PreflightProblem.PERMISSION_DENIED].format(
                    detail=detail
                ),
                detail=detail,
            )
        return PreflightReport(
            problem=PreflightProblem.IMAGE_MISSING,
            image=target,
            message=_MESSAGES[PreflightProblem.IMAGE_MISSING].format(
                image=target, detail=detail
            ),
            detail=detail,
        )

    digest = _repo_digest(inspect.stdout, target)
    return PreflightReport(
        problem=PreflightProblem.OK,
        image=target,
        message=f"Docker готов, образ {target} найден локально",
        detail=info.stdout.strip(),
        digest=digest,
    )


def ensure_docker_ready(
    *,
    image: str | None = None,
    docker_binary: str = "docker",
    timeout_seconds: float = DOCKER_PROBE_TIMEOUT_SECONDS,
    require_image: bool = True,
) -> PreflightReport:
    report = docker_preflight(
        image=image,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
        require_image=require_image,
    )
    if not report.ok:
        raise DockerPreflightError(report)
    return report


def docker_unavailable_reason(
    *,
    image: str | None = None,
    docker_binary: str = "docker",
    timeout_seconds: float = DOCKER_PROBE_TIMEOUT_SECONDS,
    require_image: bool = True,
) -> str | None:
    report = docker_preflight(
        image=image,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
        require_image=require_image,
    )
    return None if report.ok else report.message


def resolve_image_reference(
    *,
    image: str | None = None,
    docker_binary: str = "docker",
    timeout_seconds: float = DOCKER_PROBE_TIMEOUT_SECONDS,
) -> ImageReference:
    target = image or opm_image()
    report = docker_preflight(
        image=target,
        docker_binary=docker_binary,
        timeout_seconds=timeout_seconds,
    )
    if report.ok and report.digest:
        return ImageReference(image=report.digest, digest=report.digest, pinned=True)
    if report.ok:
        return ImageReference(
            image=f"{target} (тег, digest недоступен)", digest=None, pinned=False
        )
    return ImageReference(
        image=f"{target} (тег, digest не получен: {report.problem.value})",
        digest=None,
        pinned=False,
    )
