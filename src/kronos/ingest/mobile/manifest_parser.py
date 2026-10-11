"""Parses an apktool-decoded AndroidManifest.xml (plain XML, not the binary
AXML form) into the bundle id, platform, and component list this module
needs. Treats the manifest as untrusted input: malformed/crafted XML must
raise a clear, specific error rather than crash with a bare XML parser
traceback, so the orchestrator can catch it and continue gracefully.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

_ANDROID_NS = "http://schemas.android.com/apk/res/android"
_EXPORTED_ATTR = f"{{{_ANDROID_NS}}}exported"
_NAME_ATTR = f"{{{_ANDROID_NS}}}name"

_COMPONENT_TAGS = {"activity", "activity-alias", "service", "receiver", "provider"}

# component_type values this parser emits; must stay inside what
# schema.py's NODE_PROPS_ALWAYS allows for MOBILE_COMPONENT.component_type
# (a plain string column, no enum constraint there, but keeping this fixed
# set avoids ever emitting an attacker-influenced component_type string).
_TAG_TO_COMPONENT_TYPE = {
    "activity": "activity",
    "activity-alias": "activity",
    "service": "service",
    "receiver": "receiver",
    "provider": "provider",
}


class ManifestParseError(ValueError):
    """Raised for a manifest that can't be parsed or is missing required
    fields (e.g. no package attribute). Caught by the orchestrator, which
    must not crash the whole ingestion run over one malformed manifest."""


@dataclass(frozen=True)
class ParsedComponent:
    name: str
    component_type: str
    exported: bool


@dataclass(frozen=True)
class ParsedManifest:
    bundle_id: str
    platform: str
    components: list[ParsedComponent]


def _parse_bool_attr(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None  # malformed value (hostile input) — treated as "not stated"


def parse_manifest(manifest_xml_text: str) -> ParsedManifest:
    """Parse decoded AndroidManifest.xml text. Raises ManifestParseError on
    malformed XML or a missing `package` attribute — never a bare
    xml.etree exception, and never silently returns a wrong/empty bundle_id."""
    try:
        root = ET.fromstring(manifest_xml_text)
    except ET.ParseError as exc:
        raise ManifestParseError(f"malformed AndroidManifest.xml: {exc}") from exc

    bundle_id = root.attrib.get("package")
    if not bundle_id:
        raise ManifestParseError("AndroidManifest.xml has no package attribute")

    components: list[ParsedComponent] = []
    application = root.find("application")
    if application is not None:
        for el in application:
            tag = el.tag
            if tag not in _COMPONENT_TAGS:
                continue
            name = el.attrib.get(_NAME_ATTR)
            if not name:
                continue  # malformed component entry — skip, don't crash
            exported_attr = _parse_bool_attr(el.attrib.get(_EXPORTED_ATTR))
            if exported_attr is not None:
                exported = exported_attr
            else:
                # SPEC_BRIEF2: "default it FALSE (a component non-exported
                # unless the manifest says android:exported=true or an
                # intent-filter implies it)" — an intent-filter child
                # implies implicit export when exported isn't stated.
                exported = el.find("intent-filter") is not None
            components.append(
                ParsedComponent(name=name, component_type=_TAG_TO_COMPONENT_TYPE[tag], exported=exported)
            )

    return ParsedManifest(bundle_id=bundle_id, platform="android", components=components)
