"""Versioned Stem Separator product policy.

The evidence registry describes models and what they produce.  Product decisions
belong here so a registry refresh does not have to duplicate prose rules in JSON.
Unknown stem capabilities remain browseable and receive generated presentation
metadata; only workflow-like tasks are excluded.
"""

from __future__ import annotations


POLICY_VERSION = "stem-separator-v1"
PRODUCT_BACKENDS = ("audio_separator",)

PROMOTED_CAPABILITIES = (
    "vocals",
    "instrumental",
    "drums",
    "bass",
    "guitar",
    "piano",
)

GROUP_ORDER = (
    "voice",
    "rhythm",
    "guitar",
    "keys",
    "orchestral",
    "other",
)

# These are workflows or legacy preset identifiers, not independently delivered
# audio stems.  Restoration is intentionally outside the current product scope.
EXCLUDED_CAPABILITIES = {
    "cinematic_dnr",
    "decrowd",
    "denoise",
    "dereverb",
    "drum_substems",
    "karaoke",
    "multitrack_4",
    "multitrack_6",
    "multitrack_many",
    "music_sfx_removal",
    "rvc_vocals",
    "sfx_cleanup",
}

RESTORATION_CAPABILITIES = {
    "cinematic_dnr",
    "decrowd",
    "denoise",
    "dereverb",
    "music_sfx_removal",
    "sfx_cleanup",
}

COMPLEMENT_CAPABILITIES = {"instrumental", "other"}

LABEL_OVERRIDES = {
    "hihat": "Hi-hat",
    "sfx": "Sound effects",
    "rvc_vocals": "RVC vocals",
}

CAPABILITY_GROUPS = {
    "vocals": "voice",
    "lead_vocals": "voice",
    "backing_vocals": "voice",
    "choir": "voice",
    "dialogue": "voice",
    "drums": "rhythm",
    "bass": "rhythm",
    "kick": "rhythm",
    "snare": "rhythm",
    "toms": "rhythm",
    "hihat": "rhythm",
    "cymbals": "rhythm",
    "ride": "rhythm",
    "crash": "rhythm",
    "percussion": "rhythm",
    "congas": "rhythm",
    "tambourine": "rhythm",
    "timpani": "rhythm",
    "triangle": "rhythm",
    "guitar": "guitar",
    "electric_guitar": "guitar",
    "acoustic_guitar": "guitar",
    "banjo": "guitar",
    "dobro": "guitar",
    "mandolin": "guitar",
    "sitar": "guitar",
    "ukulele": "guitar",
    "piano": "keys",
    "digital_piano": "keys",
    "harpsichord": "keys",
    "organ": "keys",
    "synth": "keys",
    "keys": "keys",
    "strings": "orchestral",
    "bowed_strings": "orchestral",
    "violin": "orchestral",
    "viola": "orchestral",
    "cello": "orchestral",
    "double_bass": "orchestral",
    "wind": "orchestral",
    "woodwinds": "orchestral",
    "flute": "orchestral",
    "clarinet": "orchestral",
    "oboe": "orchestral",
    "bassoon": "orchestral",
    "brass": "orchestral",
    "trumpet": "orchestral",
    "trombone": "orchestral",
    "tuba": "orchestral",
    "french_horn": "orchestral",
    "saxophone": "orchestral",
    "harp": "orchestral",
}

# A top-level decomposition cannot include a parent and one of its children.
# This list is product taxonomy, not model evidence.
PARENT_CHILD_CAPABILITIES = {
    "vocals": {"lead_vocals", "backing_vocals", "choir"},
    "drums": {"kick", "snare", "toms", "hihat", "cymbals", "ride", "crash"},
    "guitar": {"electric_guitar", "acoustic_guitar"},
    "keys": {"piano", "digital_piano", "harpsichord", "organ", "synth"},
    "strings": {"bowed_strings", "violin", "viola", "cello", "double_bass"},
    "wind": {"woodwinds", "flute", "clarinet", "oboe", "bassoon", "saxophone"},
    "brass": {"trumpet", "trombone", "tuba", "french_horn"},
}

MULTITRACK_REQUIRED_CAPABILITIES = {"vocals", "drums", "bass"}
MULTITRACK_MIN_OUTPUTS = 4
MULTITRACK_MAX_OUTPUTS = 12
MULTITRACK_RECONSTRUCTION_MODES = {"native", "residual_to_remainder"}
MULTITRACK_VALIDATION_SCOPES = {"exact_checkpoint_smoke", "general_music_suite"}


def label_for(capability: str) -> str:
    """Return a stable generated label without blocking unknown capabilities."""

    return LABEL_OVERRIDES.get(
        capability,
        " ".join(part.capitalize() for part in capability.replace("-", "_").split("_")),
    )


def kind_for(capability: str) -> str:
    return "complement" if capability in COMPLEMENT_CAPABILITIES else "stem"


def group_for(capability: str) -> str:
    return CAPABILITY_GROUPS.get(capability, "other")


def multitrack_policy_errors(decomposition: object) -> list[str]:
    """Return policy violations for an explicit general-music decomposition."""

    if not isinstance(decomposition, dict):
        return ["must be an object"]
    errors: list[str] = []
    outputs = decomposition.get("outputs")
    if decomposition.get("scope") != "general_music":
        errors.append("scope must be general_music")
    if decomposition.get("hierarchy") != "top_level":
        errors.append("hierarchy must be top_level")
    if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
        return errors + ["outputs must be a string list"]
    output_set = set(outputs)
    if len(outputs) != len(output_set):
        errors.append("outputs must be unique")
    if not MULTITRACK_MIN_OUTPUTS <= len(outputs) <= MULTITRACK_MAX_OUTPUTS:
        errors.append(
            f"outputs must contain {MULTITRACK_MIN_OUTPUTS}-{MULTITRACK_MAX_OUTPUTS} stems"
        )
    missing = MULTITRACK_REQUIRED_CAPABILITIES - output_set
    if missing:
        errors.append("outputs are missing " + ", ".join(sorted(missing)))
    remainder = decomposition.get("remainder")
    if not isinstance(remainder, str) or remainder not in output_set:
        errors.append("remainder must name one of the outputs")
    for parent, children in PARENT_CHILD_CAPABILITIES.items():
        overlap = output_set & children
        if parent in output_set and overlap:
            errors.append(f"top-level outputs mix {parent} with {', '.join(sorted(overlap))}")
    reconstruction = decomposition.get("reconstruction")
    if not isinstance(reconstruction, dict):
        errors.append("reconstruction must be an object")
    else:
        if reconstruction.get("mode") not in MULTITRACK_RECONSTRUCTION_MODES:
            errors.append("reconstruction.mode is unsupported")
        if reconstruction.get("validated") is not True:
            errors.append("reconstruction.validated must be true")
        if reconstruction.get("validation_scope") not in MULTITRACK_VALIDATION_SCOPES:
            errors.append("reconstruction.validation_scope is unsupported")
        if not isinstance(reconstruction.get("suite"), str) or not reconstruction["suite"]:
            errors.append("reconstruction.suite is required")
        residual_ratio = reconstruction.get("residual_rms_ratio")
        if residual_ratio is not None and (
            not isinstance(residual_ratio, (int, float))
            or isinstance(residual_ratio, bool)
            or residual_ratio < 0
        ):
            errors.append("reconstruction.residual_rms_ratio must be non-negative")
    return errors
