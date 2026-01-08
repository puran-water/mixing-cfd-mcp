"""Job manager for async OpenFOAM execution.

Uses foamlib AsyncFoamCase for non-blocking solver execution.
Tracks job status, provides log access, and handles cancellation.
"""

import asyncio
import os
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# Try to import foamlib, but allow graceful degradation
try:
    from foamlib import AsyncFoamCase, FoamCase

    FOAMLIB_AVAILABLE = True
except ImportError:
    FOAMLIB_AVAILABLE = False
    AsyncFoamCase = None
    FoamCase = None


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """Represents an OpenFOAM job."""

    job_id: str
    config_id: str
    case_dir: Path
    job_type: str  # "mesh", "steady", "transient", "age"
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    error_message: str | None = None
    pid: int | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def ended_at(self) -> datetime | None:
        """Alias for completed_at (for server compatibility)."""
        return self.completed_at

    @property
    def error(self) -> str | None:
        """Alias for error_message (for server compatibility)."""
        return self.error_message

    def to_dict(self) -> dict[str, Any]:
        """Convert job to dictionary."""
        return {
            "job_id": self.job_id,
            "config_id": self.config_id,
            "case_dir": str(self.case_dir),
            "job_type": self.job_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "ended_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "error_message": self.error_message,
            "error": self.error_message,
        }


class JobManager:
    """Manages OpenFOAM job execution and lifecycle."""

    def __init__(self, work_dir: Path | None = None, max_concurrent: int = 4):
        """Initialize job manager.

        Args:
            work_dir: Base directory for case storage.
            max_concurrent: Maximum number of concurrent jobs.
        """
        self._jobs: dict[str, Job] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._work_dir = work_dir or Path.home() / ".mixing-cfd-mcp" / "cases"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    @property
    def work_dir(self) -> Path:
        """Get the working directory."""
        return self._work_dir

    @property
    def foamlib_available(self) -> bool:
        """Check if foamlib is available."""
        return FOAMLIB_AVAILABLE

    def create_job(
        self,
        config_id: str,
        case_dir: Path,
        job_type: str,
    ) -> Job:
        """Create a new job.

        Args:
            config_id: Configuration ID this job belongs to.
            case_dir: OpenFOAM case directory.
            job_type: Type of job (mesh, steady, transient, age).

        Returns:
            Created Job object.
        """
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            job_id=job_id,
            config_id=config_id,
            case_dir=Path(case_dir),
            job_type=job_type,
        )
        self._jobs[job_id] = job
        return job

    async def run_mesh_generation(
        self, config_id: str, case_dir: Path
    ) -> Job:
        """Run blockMesh (and optionally snappyHexMesh).

        Args:
            config_id: Configuration ID.
            case_dir: OpenFOAM case directory.

        Returns:
            Job object tracking the operation.
        """
        job = self.create_job(config_id, case_dir, "mesh")

        # Run in background task
        async def _run():
            await self._execute_mesh_generation(job)

        job._task = asyncio.create_task(_run())
        return job

    async def _execute_mesh_generation(self, job: Job) -> dict[str, Any]:
        """Internal: Execute mesh generation.

        Args:
            job: Job object with case_dir set.

        Returns:
            Result dictionary with success status and mesh info.
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()

        try:
            async with self._semaphore:
                case_dir = job.case_dir

                # Run blockMesh
                job.progress = 0.1
                result = await self._run_command(
                    case_dir, ["blockMesh"], "blockMesh.log"
                )

                if result["return_code"] != 0:
                    job.status = JobStatus.FAILED
                    job.error_message = f"blockMesh failed: {result.get('stderr', '')}"
                    return {"success": False, "error": job.error_message}

                job.progress = 0.5

                # Check if snappyHexMesh is needed
                snappy_dict = case_dir / "system" / "snappyHexMeshDict"
                if snappy_dict.exists():
                    result = await self._run_command(
                        case_dir, ["snappyHexMesh", "-overwrite"], "snappyHexMesh.log"
                    )

                    if result["return_code"] != 0:
                        job.status = JobStatus.FAILED
                        job.error_message = f"snappyHexMesh failed: {result.get('stderr', '')}"
                        return {"success": False, "error": job.error_message}

                job.progress = 0.7

                # Run topoSet if topoSetDict exists (creates cellSets for patches/regions)
                topo_set_dict = case_dir / "system" / "topoSetDict"
                if topo_set_dict.exists():
                    result = await self._run_command(
                        case_dir, ["topoSet"], "topoSet.log"
                    )

                    if result["return_code"] != 0:
                        job.status = JobStatus.FAILED
                        job.error_message = f"topoSet failed: {result.get('stderr', '')}"
                        return {"success": False, "error": job.error_message}

                job.progress = 0.85

                # Run createPatch if createPatchDict exists (creates patches from cellSets)
                create_patch_dict = case_dir / "system" / "createPatchDict"
                if create_patch_dict.exists():
                    result = await self._run_command(
                        case_dir, ["createPatch", "-overwrite"], "createPatch.log"
                    )

                    if result["return_code"] != 0:
                        job.status = JobStatus.FAILED
                        job.error_message = f"createPatch failed: {result.get('stderr', '')}"
                        return {"success": False, "error": job.error_message}

                job.progress = 1.0
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now()

                # Get mesh statistics
                mesh_info = await self._get_mesh_info(case_dir)

                return {
                    "success": True,
                    "mesh_info": mesh_info,
                }

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now()
            return {"success": False, "error": "Job cancelled"}
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now()
            return {"success": False, "error": str(e)}

    async def run_steady_solver(
        self, config_id: str, case_dir: Path, end_time: float = 1000.0
    ) -> Job:
        """Run steady-state solver (foamRun -solver incompressibleFluid).

        Args:
            config_id: Configuration ID.
            case_dir: OpenFOAM case directory.
            end_time: End time for the simulation.

        Returns:
            Job object tracking the operation.
        """
        job = self.create_job(config_id, case_dir, "steady")

        # Run in background task
        async def _run():
            await self._execute_steady_solver(job)

        job._task = asyncio.create_task(_run())
        return job

    async def _execute_steady_solver(self, job: Job) -> dict[str, Any]:
        """Internal: Execute steady-state solver.

        Args:
            job: Job object with case_dir set.

        Returns:
            Result dictionary with success status and solver info.
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()

        try:
            async with self._semaphore:
                case_dir = job.case_dir

                # Use foamlib if available, otherwise fall back to subprocess
                if FOAMLIB_AVAILABLE:
                    result = await self._run_with_foamlib(job)
                else:
                    result = await self._run_command(
                        case_dir,
                        ["foamRun", "-solver", "incompressibleFluid"],
                        "solver.log",
                    )

                if result.get("return_code", 1) != 0:
                    job.status = JobStatus.FAILED
                    job.error_message = result.get("error", "Solver failed")
                    return {"success": False, "error": job.error_message}

                job.progress = 1.0
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now()

                return {
                    "success": True,
                    "iterations": result.get("iterations", 0),
                    "final_residuals": result.get("residuals", {}),
                }

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now()
            return {"success": False, "error": "Job cancelled"}
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now()
            return {"success": False, "error": str(e)}

    async def run_age_computation(
        self, config_id: str, case_dir: Path
    ) -> Job:
        """Run age field computation using function object.

        The age function object should already be configured in controlDict.
        This just runs the solver which computes age automatically.

        Args:
            config_id: Configuration ID.
            case_dir: OpenFOAM case directory.

        Returns:
            Job object tracking the operation.
        """
        job = self.create_job(config_id, case_dir, "age")

        # Run in background task
        async def _run():
            await self._execute_steady_solver(job)

        job._task = asyncio.create_task(_run())
        return job

    async def _run_with_foamlib(self, job: Job) -> dict[str, Any]:
        """Run solver using foamlib AsyncFoamCase.

        Args:
            job: Job object.

        Returns:
            Result dictionary.
        """
        if not FOAMLIB_AVAILABLE:
            return {"return_code": 1, "error": "foamlib not available"}

        try:
            case = AsyncFoamCase(job.case_dir)

            # Monitor progress during run
            async def progress_monitor():
                while job.status == JobStatus.RUNNING:
                    # Check log file for iteration count
                    log_path = job.case_dir / "solver.log"
                    if log_path.exists():
                        content = log_path.read_text()
                        # Count "Time = " occurrences
                        iterations = content.count("Time = ")
                        # Estimate progress (assuming 1000 iterations typical)
                        job.progress = min(0.99, iterations / 1000)
                    await asyncio.sleep(2)

            # Start progress monitor
            monitor_task = asyncio.create_task(progress_monitor())

            # Run the solver
            await case.run()

            # Stop monitor
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            return {"return_code": 0}

        except Exception as e:
            return {"return_code": 1, "error": str(e)}

    async def _run_command(
        self,
        case_dir: Path,
        cmd: list[str],
        log_file: str,
    ) -> dict[str, Any]:
        """Run an OpenFOAM command asynchronously.

        Args:
            case_dir: Case directory.
            cmd: Command and arguments.
            log_file: Name of log file to create.

        Returns:
            Dictionary with return_code, stdout, stderr.
        """
        log_path = case_dir / log_file

        # Prepare environment with OpenFOAM paths
        env = os.environ.copy()

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=case_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await process.communicate()

        # Write log
        with open(log_path, "w") as f:
            f.write(stdout.decode())
            if stderr:
                f.write("\n--- STDERR ---\n")
                f.write(stderr.decode())

        return {
            "return_code": process.returncode,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }

    async def _get_mesh_info(self, case_dir: Path) -> dict[str, Any]:
        """Get mesh statistics from checkMesh output."""
        result = await self._run_command(case_dir, ["checkMesh"], "checkMesh.log")

        info = {
            "cells": 0,
            "faces": 0,
            "points": 0,
            "quality": "unknown",
        }

        if result["return_code"] == 0:
            output = result["stdout"]

            # Parse cell count
            for line in output.split("\n"):
                if "cells:" in line:
                    try:
                        info["cells"] = int(line.split(":")[-1].strip())
                    except ValueError:
                        pass
                elif "faces:" in line:
                    try:
                        info["faces"] = int(line.split(":")[-1].strip())
                    except ValueError:
                        pass
                elif "points:" in line:
                    try:
                        info["points"] = int(line.split(":")[-1].strip())
                    except ValueError:
                        pass

            if "Mesh OK" in output:
                info["quality"] = "ok"
            elif "Failed" in output:
                info["quality"] = "failed"

        return info

    def get_job(self, job_id: str) -> Job | None:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        config_id: str | None = None,
        status: JobStatus | None = None,
    ) -> list[Job]:
        """List jobs with optional filtering.

        Args:
            config_id: Filter by configuration ID.
            status: Filter by status.

        Returns:
            List of matching jobs.
        """
        jobs = list(self._jobs.values())

        if config_id:
            jobs = [j for j in jobs if j.config_id == config_id]

        if status:
            jobs = [j for j in jobs if j.status == status]

        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.

        Args:
            job_id: Job ID to cancel.

        Returns:
            True if job was cancelled, False if not found or not running.
        """
        job = self._jobs.get(job_id)
        if not job:
            return False

        if job.status != JobStatus.RUNNING:
            return False

        # Cancel the task if it exists
        if job._task and not job._task.done():
            job._task.cancel()

        # Kill process if PID is known
        if job.pid:
            try:
                os.kill(job.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now()
        return True

    def get_logs(
        self,
        job_id: str,
        tail: int | None = None,
        log_type: str = "solver",
    ) -> str | None:
        """Get log content for a job.

        Args:
            job_id: Job ID.
            tail: If set, return only last N lines.
            log_type: Type of log (solver, blockMesh, snappyHexMesh, checkMesh).

        Returns:
            Log content or None if not found.
        """
        job = self._jobs.get(job_id)
        if not job:
            return None

        log_file = f"{log_type}.log"
        log_path = job.case_dir / log_file

        if not log_path.exists():
            return None

        content = log_path.read_text()

        if tail:
            lines = content.split("\n")
            content = "\n".join(lines[-tail:])

        return content

    def delete_job(self, job_id: str) -> bool:
        """Delete a job from the manager.

        Does not delete case files - use delete_case for that.

        Args:
            job_id: Job ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        return False
