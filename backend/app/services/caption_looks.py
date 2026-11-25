"""Caption looks: ready-made caption designs a creator picks by eye (font, outline, box, glow,
how the key word is marked). graphics.caption_png draws them; the app shows a preview image of
each, drawn by the same code (scripts/make_look_previews.py), so what you pick is what you get.

A look sets the design. The style (or the creator's choices) still decides size, position,
case and animation - except where a look needs its own animation (karaoke, terminal).
All fonts are free for commercial use (app/assets/fonts/CREDITS.md).
"""

from dataclasses import dataclass, field
from pathlib import Path

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"


@dataclass(frozen=True)
class Look:
    id: str
    name: str
    group: str  # clean | bold | boxed | fun | elegant | tech | desi
    font: str  # file in assets/fonts, or "inter:<Weight>"
    size: int = 58  # px at 1080x1920 for "medium"; small/large scale it
    case: str | None = None  # None: as the style says
    color: str = "#FFFFFF"
    accent: str | None = None  # None: the style's accent colour
    highlight: str = "color"  # color | box | marker | underline | none
    highlight_text: str | None = None  # text colour inside a highlight box
    outline: int = 0  # px
    outline_color: str = "#000000"
    shadow: str = "soft"  # soft | hard | glow | none
    background: str = "none"  # none | box (behind each line) | band (one block behind all lines)
    background_color: str = "#000000"
    background_alpha: int = 200
    radius: int = 18
    letter_spacing: float = 0.0
    line_gap: float = 1.3
    animation: str | None = None  # forces an animation: karaoke | typewriter
    fallbacks: tuple[str, ...] = field(default_factory=tuple)  # extra fonts tried first for other scripts

    def font_path(self) -> str:
        if self.font.startswith("inter:"):
            return INTER.format(self.font.split(":", 1)[1])
        return str(FONTS / self.font)

    def fallback_paths(self) -> tuple[str, ...]:
        return tuple(str(FONTS / f) for f in self.fallbacks)


LOOKS: list[Look] = [
    # clean ------------------------------------------------------------------------------
    Look("clean", "Clean", "clean", "inter:Medium", size=52),
    Look("clean_bold", "Clean bold", "clean", "inter:ExtraBold", size=58),
    Look("soft_lower", "Soft lowercase", "clean", "inter:SemiBold", size=50, case="lower", highlight="underline"),
    Look("poppins", "Rounded", "clean", "Poppins-Bold.ttf", size=58),
    # bold creator ------------------------------------------------------------------------
    Look("punch", "Punch", "bold", "Montserrat-Black.ttf", size=66, case="upper", accent="#FFD400", outline=7, shadow="hard"),
    Look("beast", "Beast", "bold", "Anton.ttf", size=86, case="upper", accent="#3DFF6B", outline=8, shadow="hard", line_gap=1.12),
    Look("impact_box", "Impact box", "bold", "ArchivoBlack.ttf", size=60, case="upper", highlight="box", highlight_text="#000000",
         outline=5, shadow="hard"),
    Look("pop_box", "Pop box", "bold", "Poppins-Black.ttf", size=62, highlight="box", highlight_text="#FFFFFF", shadow="soft"),
    Look("karaoke", "Karaoke", "bold", "Montserrat-ExtraBold.ttf", size=62, case="upper", highlight="box", highlight_text="#FFFFFF",
         outline=5, shadow="hard", animation="karaoke"),
    Look("karaoke_color", "Karaoke colour", "bold", "Montserrat-Black.ttf", size=64, case="upper", accent="#FFD400", outline=7,
         shadow="hard", animation="karaoke"),
    Look("neon", "Neon", "bold", "Rubik-Black.ttf", size=64, color="#FFFFFF", accent="#00E5FF", shadow="glow"),
    # boxed ------------------------------------------------------------------------------
    Look("subtitle_box", "Subtitle box", "boxed", "inter:Bold", size=50, background="box", background_alpha=190, shadow="none"),
    Look("white_pill", "White pill", "boxed", "Poppins-Bold.ttf", size=54, color="#111111", background="box",
         background_color="#FFFFFF", background_alpha=245, radius=40, shadow="none"),
    Look("accent_band", "Colour band", "boxed", "BebasNeue.ttf", size=84, case="upper", accent="#FFFFFF", color="#111111", background="band",
         background_color="accent", background_alpha=235, shadow="none", line_gap=1.08),
    Look("news", "Breaking", "boxed", "Oswald-Bold.ttf", size=64, case="upper", highlight="box", highlight_text="#FFFFFF",
         accent="#E0201B", background="box", background_color="#000000", background_alpha=210, radius=6, shadow="none"),
    # fun --------------------------------------------------------------------------------
    Look("comic", "Comic", "fun", "Bangers.ttf", size=80, case="upper", color="#FFFFFF", accent="#FFD400", outline=8,
         shadow="hard", letter_spacing=2),
    Look("marker", "Marker", "fun", "PermanentMarker.ttf", size=62, highlight="marker", accent="#FFD400", shadow="soft"),
    Look("handwritten", "Handwritten", "fun", "Caveat-Bold.ttf", size=78, shadow="soft", highlight="underline"),
    Look("playful", "Playful", "fun", "LilitaOne.ttf", size=70, accent="#FF4FA3", outline=6, outline_color="#2B0A3D", shadow="hard"),
    # elegant ----------------------------------------------------------------------------
    Look("serif", "Serif", "elegant", "PlayfairDisplay-Bold.ttf", size=62, shadow="soft"),
    Look("editorial", "Editorial", "elegant", "DMSerifDisplay.ttf", size=72, case="lower", shadow="soft", highlight="underline"),
    Look("cinema", "Cinema", "elegant", "BebasNeue.ttf", size=64, case="upper", highlight="none", letter_spacing=9, shadow="soft"),
    # tech -------------------------------------------------------------------------------
    Look("mono", "Mono", "tech", "SpaceMono-Bold.ttf", size=50, highlight="box", accent="#3DFF6B", highlight_text="#000000",
         background="box", background_alpha=170, radius=8, shadow="none"),
    Look("terminal", "Terminal", "tech", "SpaceMono-Bold.ttf", size=50, color="#3DFF6B", accent="#FFFFFF", highlight="color",
         background="box", background_color="#000000", background_alpha=215, radius=6, shadow="none", animation="typewriter"),
    # desi -------------------------------------------------------------------------------
    Look("desi_bold", "Desi bold", "desi", "Baloo2-ExtraBold.ttf", size=68, accent="#FF9933", outline=6, shadow="hard",
         fallbacks=("Baloo2-ExtraBold-Deva.ttf",)),
    Look("desi_box", "Desi box", "desi", "Baloo2-ExtraBold.ttf", size=64, highlight="box", accent="#FFD400", highlight_text="#5A1A00",
         shadow="soft", fallbacks=("Baloo2-ExtraBold-Deva.ttf",)),
]

BY_ID = {lk.id: lk for lk in LOOKS}
GROUPS = {"clean": "Clean", "bold": "Bold", "boxed": "Boxed", "fun": "Fun", "elegant": "Elegant", "tech": "Tech", "desi": "Desi"}
LOOK_IDS = tuple(BY_ID)


def get(look_id: str | None) -> Look | None:
    return BY_ID.get(look_id or "")


def help_text() -> str:
    """For the style AI: pick the closest look to the references' captions."""
    return "; ".join(f"{lk.id} ({lk.name.lower()}, {lk.group})" for lk in LOOKS)
