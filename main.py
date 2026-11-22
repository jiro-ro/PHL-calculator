# CivMatics: PHL Calculator - pipe friction head loss calculator (Kivy app).

import json
import math
import os
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.utils import platform

# CONSTANTS
G = 9.81
NU_WATER = 1.004e-6

# DISPLAY UNITS:
LENGTH_TO_M = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
FLOW_TO_M3S = {
    "m³/s": 1.0,
    "ft³/s": 0.028316846592,
    "cfs": 0.028316846592,
    "L/s": 0.001,
    "gpm": 0.0000630901964,
}
VELOCITY_TO_MS = {"m/s": 1.0, "ft/s": 0.3048, "ft/sec": 0.3048}
HEAD_TO_M = LENGTH_TO_M.copy()

def convert_unit(value, unit, factors):
    return float(value) * factors[unit]

def from_si(value, unit, factors):
    return float(value) / factors[unit]

def convert_display_value(text, old_unit, new_unit, factors):  
    if not text.strip():
        return text
    try:
        value = float(text)
        si = convert_unit(value, old_unit, factors)
        return plain(from_si(si, new_unit, factors))
    except (ValueError, KeyError, ZeroDivisionError):
        return text

METHODS = ("Darcy-Weisbach", "Hazen-Williams", "Manning")
ALL_METHODS = "All methods (comparison)"
METHOD_OPTIONS = METHODS + (ALL_METHODS,)
ROUGHNESS_KEY = {"Darcy-Weisbach": "f", "Hazen-Williams": "C", "Manning": "n"}
WORST_CASE = "Worst case (all methods)"
BASIS_OPTIONS = (WORST_CASE,) + METHODS
DEFAULTS = {
    "tag": "",
    "method": ALL_METHODS,
    "Q": 0.02,
    "L": 500,
    "D": 0.15,
    "f": 0.025,
    "C": 140,
    "n": 0.011,
    "limit": 5,
    "limit_per_100": False,
    "basis": WORST_CASE,
}

# RESULT ROWS
RESULT_ROWS = (
    ("regime", "Flow Regime", None),
    ("Re", "Reynolds Number", None),
    ("A", "Cross-Sectional Area, A", "m²"),
    ("V", "Flow Velocity, V", "m/s"),
    ("f", "Darcy Friction Factor, f", "Darcy"),
    ("qp", "Power Term, Q^1.85", None),
    ("cp", "Power Term, C^1.85", None),
    ("dpw", "Power Term, D^4.87", None),
    ("R", "Hydraulic Radius, R", "m"),
    ("R43", "Power Term, R^(4/3)", "m^(4/3)"),
)
# COMPARING ROWS
COMPARE_ROWS = ("regime", "Re", "A", "V", "f", "R")
SINGLE_ROWS = {
    "Darcy-Weisbach": ("regime", "Re", "A", "V", "f"),
    "Hazen-Williams": ("A", "V", "qp", "cp", "dpw"),
    "Manning": ("A", "V", "R", "R43"),
}


def plain(value):
    return f"{value:.9f}".rstrip("0").rstrip(".")


# CALCULATION ENGINE
def area(D):
    return math.pi * D**2 / 4.0


def velocity(Q, D):
    return Q / area(D)


def reynolds(V, D, nu=NU_WATER):
    return V * D / nu


def regime_name(Re):
    if Re < 2000:
        return "laminar"
    if Re < 4000:
        return "transitional"
    return "turbulent"


def darcy_friction(Re, rel_rough):
    if Re < 2000:
        return {"f": 64.0 / Re, "laminar": True}
    a = rel_rough / 3.7
    b = 5.74 / Re**0.9
    log_term = math.log10(a + b)
    return {"f": 0.25 / log_term**2, "laminar": False,
            "a": a, "b": b, "log": log_term}


def darcy_weisbach(Q, L, D, friction_factor):
    if friction_factor <= 0:
        raise ValueError("Darcy friction factor must be greater than zero.")
    A = area(D)
    V = Q / A
    Re = reynolds(V, D)
    hf = friction_factor * (L / D) * V**2 / (2 * G)
    return {"hf": hf, "A": A, "V": V, "Re": Re,
            "f": friction_factor, "laminar": None, "given_f": True}


def hazen_williams(Q, L, D, C):
    qp = Q**1.85
    cp = C**1.85
    dpw = D**4.87
    num = 10.67 * L * qp
    den = cp * dpw
    return {"hf": num / den, "A": area(D), "V": velocity(Q, D),
            "qp": qp, "cp": cp, "dpw": dpw, "num": num, "den": den}


def manning(Q, L, D, n):
    A = area(D)
    V = Q / A
    R = D / 4.0
    R43 = R ** (4.0 / 3.0)
    hf = n**2 * L * V**2 / R43
    return {"hf": hf, "A": A, "V": V, "R": R, "R43": R43}


def methods_in_scope(method):
    return (method,) if method in METHODS else METHODS


def roughness_keys(scope):
    return tuple(ROUGHNESS_KEY[name] for name in scope)


def usable_or_default(text, default):
    try:
        value = float(text)
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def evaluate(inputs):
    Q, L, D = inputs["Q"], inputs["L"], inputs["D"]
    scope = methods_in_scope(inputs.get("method", ALL_METHODS))
    engines = {
        "Darcy-Weisbach": lambda: darcy_weisbach(Q, L, D, inputs["f"]),
        "Hazen-Williams": lambda: hazen_williams(Q, L, D, inputs["C"]),
        "Manning": lambda: manning(Q, L, D, inputs["n"]),
    }
    if inputs["limit_per_100"]:
        limit_total = inputs["limit"] * (L / 100.0)
    else:
        limit_total = inputs["limit"]

    methods = {}
    for name in scope:
        r = engines[name]()
        hf = r["hf"]
        methods[name] = {
            **r,
            "hf_per_100": hf * 100.0 / L,
            "passed": hf <= limit_total,
            "margin": limit_total - hf,
            "used_pct": 100.0 * hf / limit_total,
        }

    V = velocity(Q, D)
    flow = {"A": area(D), "V": V, "Re": reynolds(V, D)}

    basis = inputs["basis"]
    if len(scope) == 1:
        governing = scope[0]
    elif basis == WORST_CASE:
        governing = max(scope, key=lambda m: methods[m]["hf"])
    else:
        governing = basis
    return {
        "methods": methods,
        "scope": scope,
        "flow": flow,
        "limit_total": limit_total,
        "basis": basis,
        "governing": governing,
        "verdict": methods[governing]["passed"],
    }


def warnings_for(calc):
    notes = []
    scope = calc["scope"]
    Re, V = calc["flow"]["Re"], calc["flow"]["V"]
    if Re < 2000:
        if scope == ("Darcy-Weisbach",):
            notes.append(f"Laminar flow (Re = {Re:,.0f} < 2000). The friction factor "
                         "uses f = 64 / Re, which applies to laminar flow.")
        elif len(scope) > 1:
            notes.append("Laminar flow (Re < 2000). Hazen-Williams and Manning are meant "
                         "for turbulent flow, so rely on the Darcy-Weisbach result.")
        else:
            notes.append(f"Laminar flow (Re = {Re:,.0f} < 2000). {scope[0]} is meant for "
                         "turbulent flow, so its result is less reliable here. "
                         "Darcy-Weisbach also covers laminar flow.")
    elif Re < 4000:
        notes.append("Transitional flow (2000 <= Re < 4000). Results are approximate.")

    if V > 3.0:
        notes.append(f"Velocity {V:.2f} m/s is above the 3 m/s advisory limit often used "
                     "in pipe design. Check against project criteria.")
    return notes


def solution_sections(inputs, calc):
    Q, L, D = inputs["Q"], inputs["L"], inputs["D"]
    f_given, C, n = inputs["f"], inputs["C"], inputs["n"]
    lim = calc["limit_total"]
    scope = calc["scope"]
    m = calc["methods"]
    gov = calc["governing"]
    A, V = calc["flow"]["A"], calc["flow"]["V"]

    if inputs["limit_per_100"]:
        lim_text = (f"{inputs['limit']:.4g} m per 100 m, "
                    f"i.e. {lim:.4f} m for L = {L:.4g} m")
    else:
        lim_text = f"{inputs['limit']:.4g} m (total for the pipe)"

    units = inputs.get("units", {})
    q_display = from_si(Q, units.get("Q", "m³/s"), FLOW_TO_M3S)
    l_display = from_si(L, units.get("L", "m"), LENGTH_TO_M)
    d_display = from_si(D, units.get("D", "m"), LENGTH_TO_M)
    given = [
        f"Flow rate entered: Q = {q_display:.5g} {units.get('Q', 'm³/s')} "
        f"(SI internal value {Q:.6g} m³/s)",
        f"Pipe length entered: L = {l_display:.5g} {units.get('L', 'm')} "
        f"(SI internal value {L:.6g} m)",
        f"Internal diameter entered: D = {d_display:.5g} {units.get('D', 'm')} "
        f"(SI internal value {D:.6g} m)",
        f"Pipe length, L = {L:.4g} m",
        f"Internal diameter, D = {D:.4g} m",
    ]
    if "Darcy-Weisbach" in scope:
        given.append(f"Given Darcy friction factor, f = {f_given:.5f}")
    if "Hazen-Williams" in scope:
        given.append(f"Hazen-Williams coefficient, C = {C:.4g} (dimensionless)")
    if "Manning" in scope:
        given.append(f"Manning roughness, n = {n:.4g} s/m^(1/3)")
    if "Darcy-Weisbach" in scope:
        given.append(f"Kinematic viscosity of water, ν = {NU_WATER:.4g} m²/s")
    limit_unit = units.get("limit", "m")
    limit_display = from_si(inputs["limit"] if not inputs["limit_per_100"]
                            else inputs["limit"] * LENGTH_TO_M[limit_unit],
                            limit_unit, LENGTH_TO_M)
    given.append(f"Allowable head loss = {limit_display:.5g} {limit_unit}"
                 + (f" per 100 {units.get('L', 'm')}" if inputs["limit_per_100"]
                    else " total for the pipe"))
    given.append("All equations are evaluated with SI inputs (m, m/s, m³/s).")
    if "Hazen-Williams" in scope:
        given.append("Hazen-Williams uses the SI coefficient 10.67.")

    sections = [
        ("1. Given values", given),
        ("2. Cross-sectional area and velocity", [
            "## Cross-sectional area",
            "Required: A (m²)",
            "Formula: A = π D² / 4",
            f"Substitution: A = π × {D:.4g}² / 4 = {A:.6f} m²",
            "## Flow velocity",
            "Required: V (m/s)",
            "Formula: V = Q / A",
            f"Substitution: V = {Q:.4g} / {A:.6f} = {V:.4f} m/s",
            f"Final answer: A = {A:.5f} m², V = {V:.4f} m/s",
        ]),
    ]

    def add(title, body):
        sections.append((f"{len(sections) + 1}. {title}", body))

    if "Darcy-Weisbach" in scope:
        dw = m["Darcy-Weisbach"]
        darcy = [
            "Required: friction head loss hf (m)",
            "## Step 1: Reynolds number",
            "Formula: Re = V D / ν",
            f"Substitution: Re = {V:.4f} × {D:.4g} / {NU_WATER:.4g} = {dw['Re']:,.0f}",
            f"Flow regime: {regime_name(dw['Re'])}",
            "## Step 2: Darcy friction factor",
            "The problem gives the Darcy friction factor directly; no roughness equation is needed.",
            f"Given value: f = {dw['f']:.5f}",
            "## Step 3: Friction head loss",
            "Formula: hf = f (L / D) V² / (2g), with g = 9.81 m/s²",
            f"Substitution: hf = {dw['f']:.5f} × ({L:.4g} / {D:.4g}) × {V:.4f}² / (2 × 9.81)",
            f"Final answer: hf = {dw['hf']:.4f} m for L = {L:.4g} m "
            f"({dw['hf_per_100']:.4f} m per 100 m)",
        ]
        add("Darcy-Weisbach solution", darcy)

    if "Hazen-Williams" in scope:
        hw = m["Hazen-Williams"]
        add("Hazen-Williams solution", [
            "Required: friction head loss hf (m)",
            "Formula: hf = 10.67 L Q^1.85 / (C^1.85 D^4.87)",
            "## Step 1: Powers",
            f"Q^1.85 = {Q:.4g}^1.85 = {hw['qp']:.4g}",
            f"C^1.85 = {C:.4g}^1.85 = {hw['cp']:.4g}",
            f"D^4.87 = {D:.4g}^4.87 = {hw['dpw']:.4g}",
            "## Step 2: Head loss",
            f"Substitution: hf = 10.67 × {L:.4g} × {hw['qp']:.4g} "
            f"/ ({hw['cp']:.4g} × {hw['dpw']:.4g})",
            f"hf = {hw['num']:.4g} / {hw['den']:.4g} = {hw['hf']:.4f} m",
            f"Final answer: hf = {hw['hf']:.4f} m for L = {L:.4g} m "
            f"({hw['hf_per_100']:.4f} m per 100 m)",
        ])

    if "Manning" in scope:
        mn = m["Manning"]
        add("Manning solution", [
            "Required: friction head loss hf (m)",
            "## Step 1: Hydraulic radius",
            "Formula: R = A / P = D / 4 (full circular pipe)",
            f"Substitution: R = {D:.4g} / 4 = {mn['R']:.5f} m",
            "## Step 2: Head loss",
            "Formula: hf = n² L V² / R^(4/3)",
            f"Substitution: n² = {n:.4g}² = {n * n:.4g};  "
            f"R^(4/3) = {mn['R']:.5f}^(4/3) = {mn['R43']:.5g}",
            f"hf = {n * n:.4g} × {L:.4g} × {V:.4f}² / {mn['R43']:.5g} = {mn['hf']:.4f} m",
            f"Final answer: hf = {mn['hf']:.4f} m for L = {L:.4g} m "
            f"({mn['hf_per_100']:.4f} m per 100 m)",
        ])

    evaluation = [f"Allowable head loss for this pipe: {lim:.4f} m"]
    for name in scope:
        r = m[name]
        if r["passed"]:
            evaluation.append(
                f"{name}: hf = {r['hf']:.4f} m <= {lim:.4f} m, PASS "
                f"(margin {r['margin']:+.4f} m, {r['used_pct']:.1f}% of allowable used)")
        else:
            evaluation.append(
                f"{name}: hf = {r['hf']:.4f} m > {lim:.4f} m, FAIL "
                f"(exceeds allowable by {-r['margin']:.4f} m)")
    if len(scope) == 1:
        evaluation.append(f"Verdict basis: {gov} only (single method selected)")
    elif inputs["basis"] == WORST_CASE:
        evaluation.append(
            f"Verdict basis: worst case of the three methods, governed by {gov} "
            f"(hf = {m[gov]['hf']:.4f} m)")
    else:
        evaluation.append(f"Verdict basis: {gov} only, as selected by the user")
    if calc["verdict"]:
        evaluation.append(f"Final answer: PASS. The pipe meets the specified "
                          f"head-loss limit of {lim:.4f} m.")
    else:
        evaluation.append(f"Final answer: FAIL. The pipe does not meet the specified "
                          f"head-loss limit of {lim:.4f} m.")
    add("Engineering evaluation", evaluation)

    notes = warnings_for(calc)
    if notes:
        sections.append(("Notes and warnings", notes))
    return sections


def build_report(inputs, calc):
    if len(calc["scope"]) == 1:
        method_line = f"{'Method':<18}: {calc['scope'][0]}"
    else:
        method_line = f"{'Methods':<18}: Darcy-Weisbach, Hazen-Williams, Manning"
    lines = [
        "PIPE FRICTION HEAD LOSS REPORT",
        "=" * 64,
        f"Project / pipe ID : {inputs.get('tag') or '-'}",
        f"Generated         : {datetime.now():%Y-%m-%d %H:%M}",
        "Software          : CivMatics: PHL Calculator (v5)",
        method_line,
        "Units             : Internal calculations in SI; input/display units: "
        + ", ".join(f"{k}={v}" for k, v in inputs.get("units", {}).items()),
        "",
    ]
    for title, body in solution_sections(inputs, calc):
        heading = title.upper()
        lines += [heading, "-" * len(heading)]
        for item in body:
            if item.startswith("## "):
                lines += ["", item[3:]]
            else:
                lines.append(f"  {item}")
        lines.append("")
    lines += [
        "=" * 64,
        "Preliminary calculation. Verify against project criteria and "
        "applicable codes before use.",
    ]
    return "\n".join(lines) + "\n"


def positive(text, name):
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"'{name}' must be a number.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"'{name}' must be a finite number greater than zero.")
    return value


# UNITS
UNIT_FACTORS = {"Q": FLOW_TO_M3S, "L": LENGTH_TO_M, "D": LENGTH_TO_M, "limit": HEAD_TO_M}
UNIT_CHOICES = {
    "Q": ("m³/s", "L/s", "ft³/s", "gpm"),
    "L": ("m", "mm", "ft", "in"),
    "D": ("m", "mm", "ft", "in"),
    "limit": ("m", "mm", "ft", "in"),
}


FIELDS = [
    ("Q", "Flow rate, Q"),
    ("L", "Pipe length, L"),
    ("D", "Internal diameter, D"),
    ("f", "Darcy friction factor, f (Darcy-Weisbach)"),
    ("C", "Hazen-Williams coefficient, C (Hazen-Williams)"),
    ("n", "Manning roughness, n (Manning)"),
    ("limit", "Allowable head loss"),
]

def default_form():
    values = {"tag": "", "method": ALL_METHODS, "per100": "", "basis": WORST_CASE}
    for key, caption in FIELDS:
        values[key] = plain(DEFAULTS[key])
    for key in UNIT_CHOICES:
        values["unit_" + key] = UNIT_CHOICES[key][0]
    return values


def read_inputs(values):
    method = values["method"]
    needed = {"Q", "L", "D", "limit", *roughness_keys(methods_in_scope(method))}
    inputs = {"tag": values["tag"].strip(), "method": method}
    units = {}
    for key, caption in FIELDS:
        text = values[key].strip()
        if key in needed:
            number = positive(text, caption)
        else:
            number = usable_or_default(text, DEFAULTS[key])
        if key in UNIT_FACTORS:
            units[key] = values["unit_" + key]
            number = convert_unit(number, units[key], UNIT_FACTORS[key])
        inputs[key] = number
    inputs["units"] = units
    inputs["limit_per_100"] = values["per100"] == "1"
    if inputs["limit_per_100"]:
        inputs["limit"] = inputs["limit"] / LENGTH_TO_M[units["L"]]
    inputs["basis"] = values["basis"]
    return inputs


def inputs_to_values(inputs):
    values = default_form()
    values["tag"] = inputs.get("tag", "")
    saved_units = inputs.get("units", {})
    for key in UNIT_CHOICES:
        values["unit_" + key] = saved_units.get(key, values["unit_" + key])
    for key, caption in FIELDS:
        number = inputs.get(key, DEFAULTS[key])
        if key in UNIT_FACTORS:
            if key == "limit" and inputs.get("limit_per_100", False):
                number = number * LENGTH_TO_M[saved_units.get("L", "m")]
            number = from_si(number, values["unit_" + key], UNIT_FACTORS[key])
        values[key] = plain(number)
    values["per100"] = "1" if inputs.get("limit_per_100") else ""
    values["basis"] = inputs.get("basis", WORST_CASE)
    method = inputs.get("method", ALL_METHODS)
    values["method"] = method if method in METHOD_OPTIONS else ALL_METHODS
    return values


# TUTORIAL
TUTORIAL_STEPS = [
    ("Welcome!",
     "This calculator estimates friction head loss in a pipe using three "
     "methods: Darcy-Weisbach, Hazen-Williams and Manning. You can run one "
     "method or compare all three."),
    ("1. Enter the flow and geometry",
     "Type the flow rate Q, pipe length L and internal diameter D. Pick the "
     "unit for each from the drop-down next to its box, so there is no need "
     "to convert by hand."),
    ("2. Enter the material values",
     "Use the Darcy friction factor f for Darcy-Weisbach, the coefficient C "
     "for Hazen-Williams, and the roughness n for Manning. Only the values "
     "for the chosen method are needed."),
    ("3. Set the allowable limit",
     "Enter the maximum allowable head loss. Tick 'Allowable loss is per 100 "
     "length units' if your limit is given per 100 of pipe length."),
    ("4. Read the results",
     "Each method is shown with its head loss, velocity and a PASS or FAIL "
     "indicator. PASS means the head loss is within the limit. When "
     "comparing all methods, 'Verdict basis' decides which one sets the "
     "overall result."),
    ("5. Save and review",
     "Press Save on a result to keep it, then open it again later from "
     "History. Tap Help at the top to see this guide again."),
]


#KIVY
ACCENT = (0.98, 0.50, 0.45, 1)
ACCENT_LIGHT = (1.0, 0.89, 0.87, 1)
BACKGROUND = (1.0, 0.98, 0.98, 1)
FIELD = (0.98, 0.91, 0.90, 1)
TEXT = (0.11, 0.10, 0.14, 1)
WHITE = (1, 1, 1, 1)
GOOD = (0.85, 0.96, 0.87, 1)
GOOD_TEXT = (0.12, 0.45, 0.22, 1)
BAD = (1.0, 0.85, 0.85, 1)
BAD_TEXT = (0.73, 0.10, 0.10, 1)
DROP_FACE = (1.0, 0.93, 0.92, 1)
EDGE_SHADOW = (0.74, 0.46, 0.43, 1)
EDGE_LIGHT = (1.0, 1.0, 1.0, 0.8)


def raised_edges(widget):
    with widget.canvas.after:
        Color(*EDGE_LIGHT)
        top_edge = Rectangle()
        Color(*EDGE_SHADOW)
        bottom_edge = Rectangle()

    def update(*_):
        top_edge.pos = (widget.x, widget.top - dp(2))
        top_edge.size = (widget.width, dp(2))
        bottom_edge.pos = widget.pos
        bottom_edge.size = (widget.width, dp(3))

    widget.bind(pos=update, size=update)
    update()


class ThemedSpinnerOption(SpinnerOption):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = DROP_FACE
        self.color = TEXT
        self.size_hint_y = None
        self.height = dp(44)
        raised_edges(self)


def text_label(text, bold=False, color=TEXT, size=15, halign="left"):
    label = Label(text=text, bold=bold, color=color, font_size=sp(size),
                  halign=halign, valign="middle", size_hint_y=None)
    label.bind(width=lambda widget, width: setattr(widget, "text_size", (width, None)))
    label.bind(texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(6)))
    return label


def make_button(text, action, grey=False):
    button = Button(text=text, size_hint_y=None, height=dp(48), background_normal="",
                    background_color=ACCENT_LIGHT if grey else ACCENT,
                    color=TEXT if grey else WHITE)
    button.bind(on_release=lambda *_: action())
    return button


def themed_popup(title, content, size_hint, auto_dismiss=True):
    return Popup(title=title, content=content, size_hint=size_hint,
                 auto_dismiss=auto_dismiss, background="", background_color=BACKGROUND,
                 title_color=TEXT, title_size=sp(18), separator_color=ACCENT,
                 separator_height=dp(2), overlay_color=(0, 0, 0, 0.5))


class ColorBox(BoxLayout):

    def __init__(self, color, auto_height=True, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*color)
            self.rectangle = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self.update_rectangle, size=self.update_rectangle)
        if auto_height:
            self.size_hint_y = None
            self.bind(minimum_height=self.setter("height"))

    def update_rectangle(self, *_):
        self.rectangle.pos = self.pos
        self.rectangle.size = self.size


class CollapsibleBox(BoxLayout):

    def on_touch_down(self, touch):
        return False if self.height <= 0 else super().on_touch_down(touch)

    def on_touch_move(self, touch):
        return False if self.height <= 0 else super().on_touch_move(touch)

    def on_touch_up(self, touch):
        return False if self.height <= 0 else super().on_touch_up(touch)


def vertical_list():
    column = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
    column.bind(minimum_height=column.setter("height"))
    return column


class HeadLossApp(App):
    title = "CivMatics: PHL Calculator"

    def build(self):
        Window.clearcolor = BACKGROUND
        if platform in ("win", "linux", "macosx"):
            Window.size = (430, 780)
        self.history_file = os.path.join(self.user_data_dir, "history.json")
        self.settings_file = os.path.join(self.user_data_dir, "settings.json")
        self.entries = {}
        self.unit_boxes = {}
        self.last_units = {}
        self.blocks = {}
        self.loading = False
        self.last = None  

        root = BoxLayout(orientation="vertical")
        top = ColorBox(ACCENT, auto_height=False, size_hint_y=None,
                       height=dp(52), padding=dp(8), spacing=dp(8))
        title_label = Label(text="CivMatics: PHL Calculator", bold=True, color=WHITE,
                            font_size=sp(18), halign="left", valign="middle")
        title_label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        top.add_widget(title_label)
        history_button = make_button("History", self.open_history, grey=True)
        history_button.size_hint_x = None
        history_button.width = dp(90)
        history_button.height = dp(38)
        help_button = make_button("Help", self.open_tutorial, grey=True)
        help_button.size_hint_x = None
        help_button.width = dp(70)
        help_button.height = dp(38)
        top.add_widget(help_button)
        top.add_widget(history_button)
        root.add_widget(top)

        scroll = ScrollView()
        self.page = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=dp(12))
        self.page.bind(minimum_height=self.page.setter("height"))
        scroll.add_widget(self.page)
        root.add_widget(scroll)

        root.add_widget(Label(text="\u00a9 Copyright 2026 Hi-TecX", color=(0.3, 0.3, 0.35, 1),
                              font_size=sp(13), size_hint_y=None, height=dp(30)))

        self.build_form()
        self.results = vertical_list()
        self.page.add_widget(self.results)
        self.reset()
        if not self.load_settings().get("hide_tutorial"):
            Clock.schedule_once(lambda dt: self.open_tutorial(), 0.5)
        return root

    def make_entry(self, numeric=True):
        entry = TextInput(multiline=False, write_tab=False, font_size=sp(16),
                          padding=[dp(10), dp(12)], background_normal="", background_active="",
                          background_color=FIELD, foreground_color=TEXT)
        if numeric:
            entry.input_filter = "float"
            entry.input_type = "number"
        entry.bind(on_text_validate=lambda *_: self.calculate())
        return entry

    def make_spinner(self, text, values, width=None):
        spinner = Spinner(text=text, values=values, background_normal="",
                          background_color=ACCENT_LIGHT, color=TEXT,
                          option_cls=ThemedSpinnerOption)
        raised_edges(spinner)
        if width:
            spinner.size_hint_x = None
            spinner.width = width
        return spinner

    def add_block(self, caption, *widgets):
        block = CollapsibleBox(orientation="vertical", size_hint_y=None, height=dp(76))
        block.normal_height = dp(76)
        block.add_widget(text_label(caption, size=13))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        for widget in widgets:
            row.add_widget(widget)
        block.add_widget(row)
        self.page.add_widget(block)
        return block

    def build_form(self):
        self.page.add_widget(text_label("Input data", bold=True, size=18))

        self.tag_entry = self.make_entry(numeric=False)
        self.add_block("Project / Pipe ID", self.tag_entry)

        self.method_box = self.make_spinner(ALL_METHODS, METHOD_OPTIONS)
        self.method_box.bind(text=lambda *_: self.apply_method())
        self.add_block("Method", self.method_box)

        for key, caption in FIELDS:
            entry = self.make_entry()
            self.entries[key] = entry
            widgets = [entry]
            if key in UNIT_CHOICES:
                unit_box = self.make_spinner(UNIT_CHOICES[key][0], UNIT_CHOICES[key], width=dp(100))
                unit_box.bind(text=lambda box, new_unit, k=key: self.unit_changed(k, new_unit))
                self.unit_boxes[key] = unit_box
                self.last_units[key] = unit_box.text
                widgets.append(unit_box)
            self.blocks[key] = self.add_block(caption, *widgets)

        per100_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.per100_box = CheckBox(size_hint_x=None, width=dp(44), color=ACCENT)
        per100_row.add_widget(self.per100_box)
        per100_row.add_widget(text_label("Allowable loss is per 100 length units", size=14))
        self.page.add_widget(per100_row)

        self.basis_box = self.make_spinner(WORST_CASE, BASIS_OPTIONS)
        self.blocks["basis"] = self.add_block("Verdict basis", self.basis_box)

        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        buttons.add_widget(make_button("Calculate", self.calculate))
        buttons.add_widget(make_button("Reset", self.reset, grey=True))
        self.page.add_widget(buttons)

    def get_values(self):
        values = default_form()
        values["tag"] = self.tag_entry.text
        values["method"] = self.method_box.text
        for key, entry in self.entries.items():
            values[key] = entry.text
        for key, unit_box in self.unit_boxes.items():
            values["unit_" + key] = unit_box.text
        values["per100"] = "1" if self.per100_box.active else ""
        values["basis"] = self.basis_box.text
        return values

    def set_values(self, values):
        self.loading = True
        self.tag_entry.text = values["tag"]
        self.method_box.text = values["method"]
        for key, unit_box in self.unit_boxes.items():
            unit_box.text = values["unit_" + key]
            self.last_units[key] = unit_box.text
        for key, entry in self.entries.items():
            entry.text = values[key]
        self.per100_box.active = values["per100"] == "1"
        self.basis_box.text = values["basis"]
        self.loading = False
        self.apply_method()

    def unit_changed(self, key, new_unit):
        if self.loading:
            return
        old_unit = self.last_units[key]
        entry = self.entries[key]
        entry.text = convert_display_value(entry.text, old_unit, new_unit, UNIT_FACTORS[key])
        self.last_units[key] = new_unit

    def set_visible(self, block, visible):
        block.height = block.normal_height if visible else 0
        block.opacity = 1 if visible else 0
        block.disabled = not visible

    def apply_method(self):
        scope = methods_in_scope(self.method_box.text)
        self.set_visible(self.blocks["basis"], len(scope) > 1)

    def reset(self):
        self.set_values(default_form())
        self.last = None
        self.results.clear_widgets()
        self.results.add_widget(text_label("Enter the values and press Calculate.", color=(0.29, 0.27, 0.32, 1)))

#CALCULATIONS
    def calculate(self):
        try:
            inputs = read_inputs(self.get_values())
            calc = evaluate(inputs)
        except ValueError as problem:
            self.show_message(str(problem), BAD, BAD_TEXT, head="Invalid input")
            return
        except ArithmeticError:
            self.show_message("These values are outside the range the formulas can handle.",
                              BAD, BAD_TEXT, head="Invalid input")
            return
        self.last = (inputs, calc)
        self.show_results(inputs, calc)

    def show_message(self, text, color, text_color, head=""):
        self.results.clear_widgets()
        self.add_banner(head, text, color, text_color)

    def add_banner(self, head, text, color, text_color):
        box = ColorBox(color, orientation="vertical", padding=dp(10))
        if head:
            box.add_widget(text_label(head, bold=True, color=text_color, size=16))
        box.add_widget(text_label(text, color=text_color, size=14))
        self.results.add_widget(box)

    def show_results(self, inputs, calc):
        scope = calc["scope"]
        methods = calc["methods"]
        governing = calc["governing"]
        head_unit = inputs["units"]["limit"]
        head_factor = LENGTH_TO_M[head_unit]

        self.results.clear_widgets()
        self.results.add_widget(text_label("Calculation results", bold=True, size=18))

        # FLOW NUMBERS
        captions = {key: (caption, unit) for key, caption, unit in RESULT_ROWS}
        numbers = result_numbers(calc)
        keys = SINGLE_ROWS[scope[0]] if len(scope) == 1 else COMPARE_ROWS
        grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(4))
        grid.bind(minimum_height=grid.setter("height"))
        for key in keys:
            caption, unit = captions[key]
            grid.add_widget(text_label(caption, size=14))
            grid.add_widget(text_label(f"{numbers[key]} {unit or ''}", size=14, halign="right"))
        self.results.add_widget(grid)

        # PASS OR FAIL
        for name in scope:
            r = methods[name]
            ok = r["passed"]
            box = ColorBox(GOOD if ok else BAD, orientation="vertical", padding=dp(10))
            colour = GOOD_TEXT if ok else BAD_TEXT
            box.add_widget(text_label(f"{name}: {'PASS' if ok else 'FAIL'}", bold=True, color=colour, size=16))
            box.add_widget(text_label(
                f"hf = {r['hf'] / head_factor:.4f} {head_unit}\n"
                f"Margin = {r['margin'] / head_factor:+.4f} {head_unit}\n"
                f"Used = {r['used_pct']:.1f} % of allowable", color=colour, size=14))
            self.results.add_widget(box)

        # WORST CASE
        if len(scope) == 1:
            basis_text = f"Method: {governing}"
        elif inputs["basis"] == WORST_CASE:
            basis_text = f"Verdict basis: worst case of the three methods, governing method {governing}"
        else:
            basis_text = f"Verdict basis: {governing} only"
        text = (f"Allowable head loss: {calc['limit_total']:.4f} m. {basis_text}, "
                f"hf = {methods[governing]['hf']:.4f} m.")
        if calc["verdict"]:
            self.add_banner("PASS: the pipe meets the specified head-loss limit.", text, GOOD, GOOD_TEXT)
        else:
            self.add_banner("FAIL: the pipe does not meet the specified head-loss limit.", text, BAD, BAD_TEXT)

        for note in warnings_for(calc):
            self.results.add_widget(text_label(note, size=13))

        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        buttons.add_widget(make_button("Save", self.save_result))
        self.results.add_widget(buttons)

    #TUTORIAL
    def load_settings(self):
        try:
            with open(self.settings_file, encoding="utf-8") as file:
                return json.load(file)
        except (OSError, ValueError):
            return {}

    def save_settings(self, settings):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as file:
                json.dump(settings, file)
        except OSError:
            pass

    def open_tutorial(self):
        body = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(8))
        popup = themed_popup("Quick Guide", body, (0.94, 0.9), auto_dismiss=False)

        scroll = ScrollView()
        column = vertical_list()
        scroll.add_widget(column)
        body.add_widget(scroll)

        for index, (heading, text) in enumerate(TUTORIAL_STEPS):
            column.add_widget(text_label(heading, bold=True, size=20 if index == 0 else 16))
            column.add_widget(text_label(text, size=15 if index == 0 else 14))

        hide_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        hide_box = CheckBox(size_hint_x=None, width=dp(44), color=ACCENT)
        hide_box.active = bool(self.load_settings().get("hide_tutorial"))
        hide_row.add_widget(hide_box)
        hide_row.add_widget(text_label("Do not show again", bold=True, size=15))
        body.add_widget(hide_row)

        def finish():
            settings = self.load_settings()
            settings["hide_tutorial"] = hide_box.active
            self.save_settings(settings)
            popup.dismiss()

        body.add_widget(make_button("Get started", finish))
        popup.open()

    # HISTORY
    def load_history(self):
        try:
            with open(self.history_file, encoding="utf-8") as file:
                return json.load(file)
        except (OSError, ValueError):
            return []

    def save_history(self, records):
        with open(self.history_file, "w", encoding="utf-8") as file:
            json.dump(records, file)

    def save_result(self):
        inputs, calc = self.last
        records = self.load_history()
        records.append({
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "inputs": inputs,
        })
        self.save_history(records)
        self.results.add_widget(text_label("Saved to history.", bold=True, color=GOOD_TEXT))

    def history_summary(self, inputs, calc):
        units = inputs.get("units", {})
        q_unit = units.get("Q", "m³/s")
        l_unit = units.get("L", "m")
        d_unit = units.get("D", "m")
        marks = []
        for name in METHODS:
            if name in calc["methods"]:
                marks.append(f"{name.split('-')[0]} {'PASS' if calc['methods'][name]['passed'] else 'FAIL'}")
        return (f"Q {from_si(inputs['Q'], q_unit, FLOW_TO_M3S):g} {q_unit}, "
                f"L {from_si(inputs['L'], l_unit, LENGTH_TO_M):g} {l_unit}, "
                f"D {from_si(inputs['D'], d_unit, LENGTH_TO_M):g} {d_unit}\n"
                + " | ".join(marks) + f"  ->  {'PASS' if calc['verdict'] else 'FAIL'}")

    def open_history(self):
        records = self.load_history()
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        popup = themed_popup("Calculation history", body, (0.96, 0.92))

        scroll = ScrollView()
        column = vertical_list()
        scroll.add_widget(column)
        body.add_widget(scroll)
        if not records:
            column.add_widget(text_label("No saved calculations yet. Press Save on a result to add it here."))

        for record in reversed(records):
            inputs = {**DEFAULTS, **record["inputs"]}
            calc = evaluate(inputs)
            ok = calc["verdict"]
            colour = GOOD_TEXT if ok else BAD_TEXT
            box = ColorBox(GOOD if ok else BAD, orientation="vertical", padding=dp(8), spacing=dp(4))
            box.add_widget(text_label(f"{inputs.get('tag') or 'Untitled pipe'}   ({record['saved_at']})",
                                      bold=True, color=colour, size=15))
            box.add_widget(text_label(self.history_summary(inputs, calc), color=colour, size=13))
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            row.add_widget(make_button("Open", lambda r=record: self.open_record(r, popup)))
            row.add_widget(make_button("Delete", lambda r=record: self.delete_record(r, popup), grey=True))
            box.add_widget(row)
            column.add_widget(box)

        body.add_widget(make_button("Close", popup.dismiss, grey=True))
        popup.open()

    def open_record(self, record, popup):
        inputs = {**DEFAULTS, **record["inputs"]}
        self.set_values(inputs_to_values(inputs))
        self.calculate()
        popup.dismiss()

    def delete_record(self, record, history_popup):
        def do_delete():
            self.save_history([r for r in self.load_history() if r["id"] != record["id"]])
            ask.dismiss()
            history_popup.dismiss()
            self.open_history()

        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        body.add_widget(text_label("Remove this saved calculation from the history?"))
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        buttons.add_widget(make_button("Delete", do_delete))
        buttons.add_widget(make_button("Cancel", lambda: ask.dismiss(), grey=True))
        body.add_widget(buttons)
        ask = themed_popup("Delete record?", body, (0.85, 0.35))
        ask.open()


def result_numbers(calc):
    flow = calc["flow"]
    methods = calc["methods"]
    numbers = {
        "regime": regime_name(flow["Re"]).capitalize(),
        "Re": f"{flow['Re']:,.0f}",
        "A": f"{flow['A']:.5f}",
        "V": f"{flow['V']:.4f}",
    }
    if "Darcy-Weisbach" in methods:
        numbers["f"] = f"{methods['Darcy-Weisbach']['f']:.5f}"
    if "Hazen-Williams" in methods:
        hw = methods["Hazen-Williams"]
        numbers["qp"] = f"{hw['qp']:.4g}"
        numbers["cp"] = f"{hw['cp']:.4g}"
        numbers["dpw"] = f"{hw['dpw']:.4g}"
    if "Manning" in methods:
        mn = methods["Manning"]
        numbers["R"] = f"{mn['R']:.4f}"
        numbers["R43"] = f"{mn['R43']:.5g}"
    return numbers


if __name__ == "__main__":
    HeadLossApp().run()
