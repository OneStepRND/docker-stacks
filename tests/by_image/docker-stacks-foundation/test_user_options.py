# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import logging
import pathlib
import time

import pytest  # type: ignore

from tests.utils.tracked_container import TrackedContainer

LOGGER = logging.getLogger(__name__)


def test_uid_change(container: TrackedContainer) -> None:
    """Container should change the UID of the default user."""
    logs = container.run_and_wait(
        timeout=120,  # usermod is slow so give it some time
        user="root",
        environment=["NB_UID=1010"],
        command=["bash", "-c", "id && touch /opt/conda/test-file"],
    )
    assert "uid=1010(jovyan)" in logs


def test_gid_change(container: TrackedContainer) -> None:
    """Container should change the GID of the default user."""
    logs = container.run_and_wait(
        timeout=20,
        user="root",
        environment=["NB_GID=110"],
        command=["id"],
    )
    assert "gid=110(jovyan)" in logs
    assert "groups=110(jovyan),100(users)" in logs


def test_nb_user_change(container: TrackedContainer) -> None:
    """Container should change the username (`NB_USER`) of the default user."""
    nb_user = "nayvoj"
    container.run_detached(
        user="root",
        environment=[f"NB_USER={nb_user}", "CHOWN_HOME=yes"],
        command=["sleep", "infinity"],
    )

    # Give the chown time to complete.
    # Use sleep, not wait, because the container sleeps forever.
    time.sleep(1)
    LOGGER.info(f"Checking if the user is changed to {nb_user} by the start script ...")
    output = container.get_logs()
    assert "ERROR" not in output
    assert "WARNING" not in output
    assert (
        f"username: jovyan       -> {nb_user}" in output
    ), f"User is not changed to {nb_user}"

    LOGGER.info(f"Checking {nb_user} id ...")
    command = "id"
    expected_output = f"uid=1000({nb_user}) gid=100(users) groups=100(users)"
    output = container.exec_cmd(command, user=nb_user, workdir=f"/home/{nb_user}")
    assert output == expected_output, f"Bad user {output}, expected {expected_output}"

    LOGGER.info(f"Checking if {nb_user} owns his home folder ...")
    command = f'stat -c "%U %G" /home/{nb_user}/'
    expected_output = f"{nb_user} users"
    output = container.exec_cmd(command, workdir=f"/home/{nb_user}")
    assert (
        output == expected_output
    ), f"Bad owner for the {nb_user} home folder {output}, expected {expected_output}"

    LOGGER.info(
        f"Checking if a home folder of {nb_user} contains the 'work' folder with appropriate permissions ..."
    )
    command = f'stat -c "%F %U %G" /home/{nb_user}/work'
    expected_output = f"directory {nb_user} users"
    output = container.exec_cmd(command, workdir=f"/home/{nb_user}")
    assert (
        output == expected_output
    ), f"Folder work was not copied properly to {nb_user} home folder. stat: {output}, expected {expected_output}"


def test_chown_extra(container: TrackedContainer) -> None:
    """Container should change the UID/GID of a comma-separated
    CHOWN_EXTRA list of folders."""
    logs = container.run_and_wait(
        timeout=120,  # chown is slow so give it some time
        user="root",
        environment=[
            "NB_UID=1010",
            "NB_GID=101",
            "CHOWN_EXTRA=/home/jovyan,/opt/conda/bin",
            "CHOWN_EXTRA_OPTS=-R",
        ],
        command=[
            "stat",
            "-c",
            "%n:%u:%g",
            "/home/jovyan/.bashrc",
            "/opt/conda/bin/jupyter",
        ],
    )
    assert "/home/jovyan/.bashrc:1010:101" in logs
    assert "/opt/conda/bin/jupyter:1010:101" in logs


def test_chown_home(container: TrackedContainer) -> None:
    """Container should change the NB_USER home directory owner and
    group to the current value of NB_UID and NB_GID."""
    logs = container.run_and_wait(
        timeout=120,  # chown is slow so give it some time
        user="root",
        environment=[
            "CHOWN_HOME=yes",
            "CHOWN_HOME_OPTS=-R",
            "NB_USER=kitten",
            "NB_UID=1010",
            "NB_GID=101",
        ],
        command=["stat", "-c", "%n:%u:%g", "/home/kitten/.bashrc"],
    )
    assert "/home/kitten/.bashrc:1010:101" in logs


def test_sudo(container: TrackedContainer) -> None:
    """Container should grant passwordless sudo to the default user."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["GRANT_SUDO=yes"],
        command=["sudo", "id"],
    )
    assert "uid=0(root)" in logs


def test_sudo_path(container: TrackedContainer) -> None:
    """Container should include /opt/conda/bin in the sudo secure_path."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["GRANT_SUDO=yes"],
        command=["sudo", "which", "jupyter"],
    )
    assert logs.rstrip().endswith("/opt/conda/bin/jupyter")


def test_sudo_path_without_grant(container: TrackedContainer) -> None:
    """Container should include /opt/conda/bin in the sudo secure_path."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        command=["which", "jupyter"],
    )
    assert logs.rstrip().endswith("/opt/conda/bin/jupyter")


def test_group_add(container: TrackedContainer) -> None:
    """Container should run with the specified uid, gid, and secondary
    group. It won't be possible to modify /etc/passwd since gid is nonzero, so
    additionally verify that setting gid=0 is suggested in a warning.
    """
    logs = container.run_and_wait(
        timeout=10,
        no_warnings=False,
        user="1010:1010",
        group_add=["users"],  # Ensures write access to /home/jovyan
        command=["id"],
    )
    warnings = TrackedContainer.get_warnings(logs)
    assert len(warnings) == 1
    assert "Try setting gid=0" in warnings[0]
    assert "uid=1010 gid=1010 groups=1010,100(users)" in logs


def test_set_uid(container: TrackedContainer) -> None:
    """Container should run with the specified uid and NB_USER.
    The /home/jovyan directory will not be writable since it's owned by 1000:users.
    Additionally, verify that "--group-add=users" is suggested in a warning to restore
    write access.
    """
    # This test needs to have tty disabled, the reason is explained here:
    # https://github.com/jupyter/docker-stacks/pull/2260#discussion_r2008821257
    logs = container.run_and_wait(
        timeout=10, no_warnings=False, user="1010", command=["id"], tty=False
    )
    assert "uid=1010(jovyan) gid=0(root)" in logs
    warnings = TrackedContainer.get_warnings(logs)
    assert len(warnings) == 1
    assert "--group-add=users" in warnings[0]


def test_set_uid_and_nb_user(container: TrackedContainer) -> None:
    """Container should run with the specified uid and NB_USER."""
    logs = container.run_and_wait(
        timeout=10,
        no_warnings=False,
        user="1010",
        environment=["NB_USER=kitten"],
        group_add=["users"],  # Ensures write access to /home/jovyan
        command=["id"],
    )
    assert "uid=1010(kitten) gid=0(root)" in logs
    warnings = TrackedContainer.get_warnings(logs)
    assert len(warnings) == 1
    assert "user is kitten but home is /home/jovyan" in warnings[0]


def test_container_not_delete_bind_mount(
    container: TrackedContainer, tmp_path: pathlib.Path
) -> None:
    """Container should not delete host system files when using the (docker)
    -v bind mount flag and mapping to /home/jovyan.
    """
    host_data_dir = tmp_path / "data"
    host_data_dir.mkdir()
    host_file = host_data_dir / "foo.txt"
    host_file.write_text("some-content")

    container.run_and_wait(
        timeout=10,
        user="root",
        working_dir="/home/",
        environment=[
            "NB_USER=user",
            "CHOWN_HOME=yes",
        ],
        volumes={host_data_dir: {"bind": "/home/jovyan/data", "mode": "rw"}},
        command=["ls"],
    )
    assert host_file.read_text() == "some-content"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("enable_root", [False, True])
def test_jupyter_env_vars_to_unset(
    container: TrackedContainer, enable_root: bool
) -> None:
    """Environment variables names listed in JUPYTER_ENV_VARS_TO_UNSET
    should be unset in the final environment."""
    root_args = {"user": "root"} if enable_root else {}
    logs = container.run_and_wait(
        timeout=10,
        environment=[
            "JUPYTER_ENV_VARS_TO_UNSET=SECRET_ANIMAL,UNUSED_ENV,SECRET_FRUIT",
            "FRUIT=bananas",
            "SECRET_ANIMAL=cats",
            "SECRET_FRUIT=mango",
        ],
        command=[
            "bash",
            "-c",
            "echo I like ${FRUIT} and ${SECRET_FRUIT:-stuff}, and love ${SECRET_ANIMAL:-to keep secrets}!",
        ],
        **root_args,  # type: ignore
    )
    assert "I like bananas and stuff, and love to keep secrets!" in logs


def test_secure_path(container: TrackedContainer, tmp_path: pathlib.Path) -> None:
    """Make sure that the sudo command has conda's python (not system's) on PATH.
    See <https://github.com/jupyter/docker-stacks/issues/1053>.
    """
    host_data_dir = tmp_path / "data"
    host_data_dir.mkdir()
    host_file = host_data_dir / "wrong_python.sh"
    host_file.write_text('#!/bin/bash\necho "Wrong python executable invoked!"')
    host_file.chmod(0o755)

    logs = container.run_and_wait(
        timeout=10,
        user="root",
        volumes={host_file: {"bind": "/usr/bin/python", "mode": "ro"}},
        command=["python", "--version"],
    )
    assert "Wrong python" not in logs
    assert "Python" in logs


def test_startsh_multiple_exec(container: TrackedContainer) -> None:
    """If start.sh is executed multiple times check that configuration only occurs once."""
    logs = container.run_and_wait(
        timeout=10,
        no_warnings=False,
        user="root",
        environment=["GRANT_SUDO=yes"],
        command=["start.sh", "sudo", "id"],
    )
    assert "uid=0(root)" in logs
    warnings = TrackedContainer.get_warnings(logs)
    assert len(warnings) == 1
    assert (
        "WARNING: start.sh is the default ENTRYPOINT, do not include it in CMD"
        in warnings[0]
    )


def test_rootless_triplet_change(container: TrackedContainer) -> None:
    """Container should change the username (`NB_USER`), the UID and the GID of the default user."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["NB_USER=root", "NB_UID=0", "NB_GID=0"],
        command=["id"],
    )
    assert "uid=0(root)" in logs
    assert "gid=0(root)" in logs
    assert "groups=0(root)" in logs


def test_rootless_triplet_home(container: TrackedContainer) -> None:
    """Container should change the home directory for triplet NB_USER=root, NB_UID=0, NB_GID=0."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["NB_USER=root", "NB_UID=0", "NB_GID=0"],
        command=["bash", "-c", "echo HOME=${HOME} && getent passwd root"],
    )
    assert "HOME=/home/root" in logs
    assert "root:x:0:0:root:/home/root:/bin/bash" in logs


def test_rootless_triplet_sudo(container: TrackedContainer) -> None:
    """Container should not be started with sudo for triplet NB_USER=root, NB_UID=0, NB_GID=0."""
    logs = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["NB_USER=root", "NB_UID=0", "NB_GID=0"],
        command=["env"],
    )
    assert "SUDO" not in logs


def test_log_stderr(container: TrackedContainer) -> None:
    """Logs should go to stderr, not stdout"""
    stdout, stderr = container.run_and_wait(
        timeout=10,
        user="root",
        environment=["NB_USER=root", "NB_UID=0", "NB_GID=0"],
        command=["echo", "stdout"],
        split_stderr=True,
    )
    # no logs should be on stdout
    assert stdout.strip() == "stdout"
    # check that logs were captured
    assert "Entered start.sh" in stderr
    assert "Running as root" in stderr
