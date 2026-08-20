"""Give a generated FCStd a fixed, engineering-CAD appearance.

A headless FreeCAD writes no ``GuiDocument.xml`` — the probe is unambiguous:
``obj.ViewObject`` is ``None`` when ``App.GuiUp`` is false, and
``FreeCADGui.setupWithoutGUI()`` does not change that (it initialises the Gui
module but creates no view providers). So every part this system has ever built
was saved with **no view state at all**, and took whatever appearance the
opening machine's preferences happened to supply. Two users opening the same
part saw two different parts, and neither matched the studio viewport.

``ShapeMaterial`` looked like the fix and is not. It is an App-level property,
so it does survive a headless save — but it serialises as *only a UUID*
(``<PropertyMaterial uuid="..."/>``), inline colour overrides are discarded on
reload, and FreeCAD's own ``PartDesignExample.FCStd`` shows the two are not
kept in step: its Body carries the "Default" material UUID while its stored
``ShapeAppearance`` holds the classic 0.2/0.8 grey, which is not that
material's colour. The renderer reads ``ShapeAppearance``. That is what has to
be written.

So this writes the Gui document itself. The format is FreeCAD's, read back off
a file FreeCAD wrote (``data/examples/PartDesignExample.FCStd``):

* ``GuiDocument.xml`` holds one ``<ViewProvider>`` per object; an object with no
  entry simply falls back to defaults, which is what makes it safe to describe
  only the Body and leave the rest alone.
* ``App::PropertyColor`` is a packed ``0xRRGGBBAA`` written little-endian —
  the example's ``LineColor value="421075455"`` is ``0x191919FF``.
* ``ShapeAppearance`` is an ``App::PropertyMaterialList`` held in a *separate
  archive member*, 40 bytes for a one-entry list: ``uint32`` count, four packed
  colours (ambient, diffuse, specular, emissive), ``float32`` shininess, then
  four reserved words (16 bytes; the blob is exactly 40 bytes long).

What this module cannot do is set the viewport *background* or the
anti-aliasing level. Those are FreeCAD application preferences
(``user.cfg``), not document state — no file can carry them, and a generated
part has no business rewriting a user's global settings.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import tempfile
import zipfile

# --------------------------------------------------------------------------- #
# the appearance
# --------------------------------------------------------------------------- #
#: Machined aluminium, matched to the studio viewport's ``CAD_SURFACE``
#: (``orionflow-ui/src/lib/cadAppearance.ts``) so the part a user downloads
#: looks like the part they were shown.
#:
#: FreeCAD's shading is Phong over these four terms, not the viewer's PBR, so
#: this is a deliberate translation rather than a copy of the same numbers:
#: the diffuse term carries the aluminium grey, a low specular with a modest
#: shininess gives the soft sheen of a machined face, and the ambient term is
#: kept high enough that faces turned away from the light stay readable — which
#: is what an engineer needs from a viewport and what a "realistic" render
#: deliberately withholds.
DIFFUSE = (0.7608, 0.7843, 0.8118)   # #c2c7cf
AMBIENT = (0.2500, 0.2600, 0.2700)
SPECULAR = (0.1600, 0.1650, 0.1700)
EMISSIVE = (0.0, 0.0, 0.0)
#: Low on purpose. A high shininess is what makes a part read as glossy plastic
#: or a game asset; a machined metal face has a broad, dull highlight.
SHININESS = 0.18

#: Edges, dark but not pure black, so they describe the geometry without
#: cartooning it.
LINE_COLOR = (0.0980, 0.1020, 0.1176)  # #191a1e
LINE_WIDTH = 1.8
POINT_SIZE = 2.0

#: Tessellation. FreeCAD's defaults (0.5 / 28.5) visibly facet a fillet; these
#: are the same "smooth where it matters" intent as the 0.05 mm linear
#: deflection used for the STL export in ``orion/build_export_fc.py``.
DEVIATION = 0.15
ANGULAR_DEFLECTION = 12.0

#: ``ViewProviderPartExt`` display modes, in FreeCAD's own order. 0 is
#: "Flat Lines" — shaded faces *with* their edges drawn, which is the
#: engineering-viewport read the whole exercise is aimed at.
DISPLAY_FLAT_LINES = 0
#: ``Lighting``: 1 == "Two side", so an inward-facing face on an open shell is
#: lit rather than rendering black.
LIGHTING_TWO_SIDE = 1


def pack_color(rgb: tuple, alpha: float = 1.0) -> int:
    """(r, g, b) floats in 0..1 -> FreeCAD's packed ``0xRRGGBBAA`` integer."""
    r, g, b = (max(0, min(255, int(round(c * 255)))) for c in rgb)
    a = max(0, min(255, int(round(alpha * 255))))
    return (r << 24) | (g << 16) | (b << 8) | a


def encode_material_list(
    ambient: tuple = AMBIENT,
    diffuse: tuple = DIFFUSE,
    specular: tuple = SPECULAR,
    emissive: tuple = EMISSIVE,
    shininess: float = SHININESS,
) -> bytes:
    """A one-entry ``App::PropertyMaterialList`` blob, byte-for-byte as FreeCAD
    writes it. See the module docstring for the layout."""
    return struct.pack(
        "<I4IfIIII",
        1,
        pack_color(ambient),
        pack_color(diffuse),
        pack_color(specular),
        pack_color(emissive),
        float(shininess),
        0,
        0,
        0,
        0,
    )


# --------------------------------------------------------------------------- #
# the Gui document
# --------------------------------------------------------------------------- #
_APPEARANCE_MEMBER = "ShapeAppearance"


def _body_view_provider(name: str) -> str:
    """The ``<ViewProvider>`` element for the solid the user actually sees."""
    return f"""        <ViewProvider name="{name}" expanded="0" treeRank="0">
            <Properties Count="10" TransientCount="0">
                <Property name="ShapeAppearance" type="App::PropertyMaterialList" status="1">
                    <MaterialList file="{_APPEARANCE_MEMBER}" version="3"/>
                </Property>
                <Property name="LineColor" type="App::PropertyColor" status="1">
                    <PropertyColor value="{pack_color(LINE_COLOR)}"/>
                </Property>
                <Property name="PointColor" type="App::PropertyColor" status="1">
                    <PropertyColor value="{pack_color(LINE_COLOR)}"/>
                </Property>
                <Property name="LineWidth" type="App::PropertyFloatConstraint" status="1">
                    <Float value="{LINE_WIDTH:.16f}"/>
                </Property>
                <Property name="PointSize" type="App::PropertyFloatConstraint" status="1">
                    <Float value="{POINT_SIZE:.16f}"/>
                </Property>
                <Property name="Transparency" type="App::PropertyPercent" status="1">
                    <Integer value="0"/>
                </Property>
                <Property name="DisplayMode" type="App::PropertyEnumeration" status="1">
                    <Integer value="{DISPLAY_FLAT_LINES}"/>
                </Property>
                <Property name="Lighting" type="App::PropertyEnumeration" status="1">
                    <Integer value="{LIGHTING_TWO_SIDE}"/>
                </Property>
                <Property name="Deviation" type="App::PropertyFloatConstraint" status="1">
                    <Float value="{DEVIATION:.16f}"/>
                </Property>
                <Property name="AngularDeflection" type="App::PropertyAngle" status="1">
                    <Float value="{ANGULAR_DEFLECTION:.16f}"/>
                </Property>
            </Properties>
        </ViewProvider>
"""


def _axis_angle(eye, target, up=(0.0, 0.0, 1.0)):
    """Axis-angle for a camera at ``eye`` looking at ``target``, as Coin wants it.

    Coin stores ``orientation`` as ``ax ay az angle``, describing the rotation
    of the camera frame — camera-local -Z is the view direction and +Y is up.
    Built from the frame directly rather than from a hand-copied constant, so
    the view is verifiably the one intended instead of a magic quaternion.
    """
    import math

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def norm(v):
        m = math.sqrt(sum(c * c for c in v)) or 1.0
        return (v[0] / m, v[1] / m, v[2] / m)

    z = norm(sub(eye, target))          # camera +Z points back toward the eye
    x = norm(cross(up, z))
    y = cross(z, x)
    # column-major rotation matrix [x y z]
    m = ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))
    trace = m[0][0] + m[1][1] + m[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
    s = math.sin(angle)
    if abs(s) < 1e-9:
        return (0.0, 0.0, 1.0, 0.0)
    ax = ((m[2][1] - m[1][2]) / (2 * s),
          (m[0][2] - m[2][0]) / (2 * s),
          (m[1][0] - m[0][1]) / (2 * s))
    return (ax[0], ax[1], ax[2], angle)


def build_camera(bbox=None) -> str:
    """An orthographic, axonometric view framed on the part.

    Orthographic because that is the projection engineering drawings and CAD
    viewports use — parallel edges stay parallel and a dimension reads the same
    anywhere on screen. The eye sits on (1, -1, 1) from the part centre, which
    is FreeCAD's own axonometric direction and shows three faces at once.

    Generously framed on purpose: ``height`` is set from the bounding *sphere*,
    not the tightest fit, so no part can open partly off-screen. With no bbox
    the element is omitted entirely rather than guessed — FreeCAD then supplies
    its default view, which is a far better failure than a camera pointed at
    empty space.
    """
    import math

    if not bbox or len(bbox) != 6:
        return ""
    xmin, ymin, zmin, xmax, ymax, zmax = (float(v) for v in bbox)
    center = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)
    diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
    radius = max(diag / 2, 1e-3)

    d = radius * 3.0
    k = 1.0 / math.sqrt(3.0)
    eye = (center[0] + d * k, center[1] - d * k, center[2] + d * k)
    ax, ay, az, angle = _axis_angle(eye, center)
    height = radius * 2.6

    settings = (
        "OrthographicCamera {\n"
        "  viewportMapping ADJUST_CAMERA\n"
        f"  position {eye[0]:.6f} {eye[1]:.6f} {eye[2]:.6f}\n"
        f"  orientation {ax:.7f} {ay:.7f} {az:.7f}  {angle:.7f}\n"
        f"  nearDistance {max(d - radius * 2, radius * 0.01):.6f}\n"
        f"  farDistance {d + radius * 3:.6f}\n"
        "  aspectRatio 1\n"
        f"  focalDistance {d:.6f}\n"
        f"  height {height:.6f}\n"
        "\n}\n"
    )
    esc = (settings.replace("&", "&amp;").replace(chr(34), "&quot;")
           .replace("<", "&lt;").replace(">", "&gt;")
           .replace("\n", "&#10;"))
    return f'    <Camera settings="{esc}"/>\n'


def build_gui_document(body_names: list, bbox=None) -> str:
    providers = "".join(_body_view_provider(n) for n in body_names)
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<!--\n FreeCAD Document, see https://www.freecad.org for more information\n-->\n"
        '<Document SchemaVersion="1" HasExpansion="1">\n'
        '    <Expand  count="0">\n'
        "    </Expand>\n"
        f'    <ViewProviderData Count="{len(body_names)}">\n'
        f"{providers}"
        "    </ViewProviderData>\n"
        '    <CameraSettings/>\n'
        "</Document>\n"
    )


def body_names(fcstd_path: str) -> list:
    """Names of the ``PartDesign::Body`` objects in a saved document.

    Read out of ``Document.xml`` rather than by reopening the file in FreeCAD:
    this runs after the document is closed, and paying a second kernel startup
    to learn one name would be absurd.
    """
    with zipfile.ZipFile(fcstd_path) as z:
        xml = z.read("Document.xml").decode("utf-8", "replace")
    names = []
    for m in re.finditer(r'<Object name="([^"]+)"[^>]*>', xml):
        names.append(m.group(1))
    typed = re.findall(
        r'<Object type="PartDesign::Body" name="([^"]+)"', xml
    ) or re.findall(r'name="([^"]+)" type="PartDesign::Body"', xml)
    if typed:
        return typed
    # The object list and the type list are written in the same order, so fall
    # back to matching the conventional name rather than guessing.
    return [n for n in names if n == "Body"] or (["Body"] if names else [])


def apply(fcstd_path: str, bbox=None) -> bool:
    """Rewrite ``fcstd_path`` with a GuiDocument giving it the CAD appearance.

    Returns True when view state was written. Rewrites through a temporary file
    and replaces atomically: a half-written archive would cost the user the
    geometry, which is a far worse outcome than an unstyled part.
    """
    if not os.path.exists(fcstd_path):
        return False
    tmp = None
    try:
        bodies = body_names(fcstd_path)
        if not bodies:
            return False

        gui_xml = build_gui_document(bodies, bbox)
        blob = encode_material_list()

        fd, tmp = tempfile.mkstemp(
            suffix=".FCStd", dir=os.path.dirname(os.path.abspath(fcstd_path))
        )
        os.close(fd)
        with zipfile.ZipFile(fcstd_path) as src, zipfile.ZipFile(
            tmp, "w", zipfile.ZIP_DEFLATED
        ) as dst:
            for item in src.infolist():
                if item.filename in ("GuiDocument.xml", _APPEARANCE_MEMBER):
                    continue  # replaced below
                dst.writestr(item, src.read(item.filename))
            dst.writestr("GuiDocument.xml", gui_xml)
            dst.writestr(_APPEARANCE_MEMBER, blob)
        shutil.move(tmp, fcstd_path)
        return True
    except Exception:  # noqa: BLE001 — appearance must never cost the geometry
        # The original file is untouched until the final move, so failing here
        # leaves a correct, merely unstyled part rather than a damaged one.
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False
