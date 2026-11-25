"""Core package for automated TAAFT movie generation."""
from core.continuity import ContinuityProcessor
from core.scriptwriter import GeminiScriptwriter
from core.browser_worker import TAAFTBrowserWorker
from core.movie_compiler import MovieCompiler
from core.pipeline_manager import pipeline, PipelineManager

__all__ = [
    "ContinuityProcessor",
    "GeminiScriptwriter",
    "TAAFTBrowserWorker",
    "MovieCompiler",
    "pipeline",
    "PipelineManager"
]
