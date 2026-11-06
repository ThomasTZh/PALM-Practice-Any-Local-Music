"""First-run setup: checks, tools, environments, models and setup jobs."""

from basseparate.setup.checks import system_checks
from basseparate.setup.download import download_file, download_verified
from basseparate.setup.environments import ENV_VARIANTS, create_environment, environments_status
from basseparate.setup.errors import DownloadError, SetupError, SetupInstallError
from basseparate.setup.models import install_model, install_models
from basseparate.setup.routes import install
from basseparate.setup.service import SetupService
from basseparate.setup.state import SetupStateStore
from basseparate.setup.tools import install_tools, tools_status

__all__ = [
    "ENV_VARIANTS",
    "DownloadError",
    "SetupError",
    "SetupInstallError",
    "SetupService",
    "SetupStateStore",
    "create_environment",
    "download_file",
    "download_verified",
    "environments_status",
    "install_model",
    "install_models",
    "install",
    "install_tools",
    "system_checks",
    "tools_status",
]
