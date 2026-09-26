"""Parse MCNP data cards into Studio sources, tallies, and run settings.

Standard library only (no numpy, no openmc).
Units: lengths cm, energies MeV.
"""
import math
import re

ALLOWED_SDEF_KEYS = {'PAR', 'POS', 'RAD', 'EXT', 'AXS', 'X', 'Y', 'Z', 'VEC', 'DIR', 'ERG', 'WGT'}
ALLOWED_FMESH_KEYS = {'GEOM', 'ORIGIN', 'IMESH', 'IINTS', 'JMESH', 'JINTS', 'KMESH', 'KINTS', 'EMESH', 'EINTS', 'AXS', 'VEC', 'OUT'}
SILENT_CARD_RE = re.compile(r'^(M\d+|MT\d+|MX\d+|\*?TR\d+|IMP:.*|VOL|AREA|PRINT|PRDMP)$', re.IGNORECASE)


# Malformed numbers or shortcuts raise these; parse() turns them into a refusal
# of the one card instead of failing the whole import.
BAD_INPUT = (ValueError, IndexError, ZeroDivisionError, OverflowError)


def _unreadable(card, e):
    return {"card": card["name"], "line": card["line"], "reason": f"couldn't read the card ({e})"}


class ParseRefusal(Exception):
    def __init__(self, card, line, reason):
        super().__init__(reason)
        self.card = card
        self.line = line
        self.reason = reason


def fmt_num(v):
    """Format number using .15g as required by Studio formats."""
    return format(float(v), ".15g")


def expand_shortcuts(tokens):
    """Expand MCNP shortcuts (nR, nI, nLOG/nILOG) in numeric lists.

    Raises ParseRefusal if nJ or nM is encountered.
    """
    out = []
    for t in tokens:
        if re.match(r'^\d*[jJmM]$', t):
            raise ParseRefusal(None, None, "the nJ/nM shortcuts aren't imported")

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        m_r = re.match(r'^(\d*)[rR]$', tok)
        m_i = re.match(r'^(\d*)[iI]$', tok)
        m_log = re.match(r'^(\d*)(?:ILOG|LOG)$', tok, re.IGNORECASE)
        if m_r:
            if not out:
                raise ValueError("R shortcut without previous value")
            n = int(m_r.group(1) or 1)
            val = out[-1]
            out.extend([val] * n)
            i += 1
        elif m_i:
            if not out:
                raise ValueError("I shortcut without previous value")
            if i + 1 >= len(tokens):
                raise ValueError("I shortcut without next value")
            n = int(m_i.group(1) or 1)
            prev_val = out[-1]
            next_val = float(tokens[i + 1].replace('D', 'E').replace('d', 'e'))
            step = (next_val - prev_val) / (n + 1)
            for k in range(1, n + 1):
                out.append(prev_val + k * step)
            i += 1
        elif m_log:
            if not out:
                raise ValueError("LOG shortcut without previous value")
            if i + 1 >= len(tokens):
                raise ValueError("LOG shortcut without next value")
            n = int(m_log.group(1) or 1)
            prev_val = out[-1]
            next_val = float(tokens[i + 1].replace('D', 'E').replace('d', 'e'))
            if prev_val <= 0 or next_val <= 0:
                raise ValueError("LOG shortcut with non-positive values")
            ratio = (next_val / prev_val) ** (1.0 / (n + 1))
            for k in range(1, n + 1):
                out.append(prev_val * (ratio ** k))
            i += 1
        else:
            val = float(tok.replace('D', 'E').replace('d', 'e'))
            out.append(val)
            i += 1
    return out


def _read_data_cards(text):
    """Read lines of the third block (data cards) and assemble continued cards.

    Returns a list of dicts: {'name': str, 'body': str, 'line': int}.
    """
    lines = text.splitlines()
    idx = 0
    # Step 0: Check MESSAGE:
    if idx < len(lines) and lines[idx].lstrip().upper().startswith("MESSAGE:"):
        while idx < len(lines) and lines[idx].strip():
            idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
    # Line 1 (or next non-blank after MESSAGE) is title
    if idx < len(lines):
        idx += 1
    # Block 1: cells
    while idx < len(lines) and lines[idx].strip():
        idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    # Block 2: surfaces
    while idx < len(lines) and lines[idx].strip():
        idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    # Block 3: data cards
    raw_cards = []
    current_card = None
    continued_by_amp = False

    while idx < len(lines):
        line_num = idx + 1
        raw = lines[idx]
        idx += 1
        exp = raw.expandtabs(8)
        if not exp.strip():
            # Blank line ends block 3
            break
        # Comment line: c or C in col 1..5 followed by space or end of line
        if re.match(r'^[ ]{0,4}[cC](\s.*|$)', exp):
            continue
        # Inline comment
        content = exp.split('$', 1)[0]
        if not content.strip():
            continue
        leading_spaces = len(content) - len(content.lstrip(' '))
        is_cont = (current_card is not None) and (continued_by_amp or leading_spaces >= 5)
        stripped_trailing = content.rstrip()
        has_amp = stripped_trailing.endswith('&')
        line_text = stripped_trailing[:-1] if has_amp else content

        if is_cont:
            current_card["body"] += " " + line_text.strip()
        else:
            if current_card is not None:
                raw_cards.append(current_card)
            m = re.match(r'^\s*([^\s=]+)(.*)$', line_text, re.DOTALL)
            if m:
                current_card = {"name": m.group(1), "body": m.group(2).strip(), "line": line_num}
            else:
                current_card = None
        continued_by_amp = has_amp

    if current_card is not None:
        raw_cards.append(current_card)
    return raw_cards


def _parse_key_values(body, allowed_keys, special_values=None):
    """Parse KEY=VAL or KEY VAL pairs from card body."""
    text = body.replace('=', ' = ')
    raw_tokens = text.split()
    pairs = {}
    i = 0
    current_key = None
    current_vals = []
    specials = set(special_values or ())

    def is_num(tok):
        return bool(re.match(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$', tok))

    def is_dist(tok):
        return bool(re.match(r'^[dD]\d+$', tok))

    def is_sc(tok):
        return bool(re.match(r'^\d*(?:[rRiIjJmM]|ILOG|LOG)$', tok, re.IGNORECASE))

    while i < len(raw_tokens):
        tok = raw_tokens[i]
        if tok == '=':
            i += 1
            continue
        has_eq = (i + 1 < len(raw_tokens) and raw_tokens[i + 1] == '=')
        is_kw = False
        if has_eq:
            is_kw = True
        elif tok.upper() in allowed_keys:
            if current_key and tok.upper() in specials and not current_vals:
                is_kw = False
            else:
                is_kw = True
        elif not is_num(tok) and not is_dist(tok) and not is_sc(tok) and tok.upper() not in specials:
            is_kw = True

        if is_kw:
            if current_key is not None:
                pairs[current_key] = current_vals
            current_key = tok.upper()
            current_vals = []
            if has_eq:
                i += 2
            else:
                i += 1
        else:
            current_vals.append(tok)
            i += 1

    if current_key is not None:
        pairs[current_key] = current_vals
    return pairs


def parse(text: str) -> dict:
    """Parse deck text into sources, tallies, settings, refused, and notes."""
    cards = _read_data_cards(text)

    sources = []
    tallies = []
    settings = {}
    refused = []
    notes = []

    # Map cards by category
    sdef_cards = []
    si_cards = {}   # int -> card
    sp_cards = {}   # int -> card
    sb_cards = {}   # int -> card
    ds_cards = {}   # int -> card
    kcode_card = None
    ksrc_card = None
    mode_card = None
    nps_card = None

    cell_tallies = {}  # n -> card
    companion_cards = {}  # n -> list of cards
    fmesh_cards = {}  # n -> card

    unrecognized_cards = []

    for card in cards:
        name = card["name"]
        uname = name.upper()

        if uname == 'SDEF':
            sdef_cards.append(card)
            continue

        m_si = re.match(r'^SI(\d+)$', uname)
        if m_si:
            si_cards[int(m_si.group(1))] = card
            continue

        m_sp = re.match(r'^SP(\d+)$', uname)
        if m_sp:
            sp_cards[int(m_sp.group(1))] = card
            continue

        m_sb = re.match(r'^SB(\d+)$', uname)
        if m_sb:
            sb_cards[int(m_sb.group(1))] = card
            continue

        m_ds = re.match(r'^DS(\d+)$', uname)
        if m_ds:
            ds_cards[int(m_ds.group(1))] = card
            continue

        if uname == 'KCODE':
            kcode_card = card
            continue

        if uname == 'KSRC':
            ksrc_card = card
            continue

        if uname == 'MODE':
            mode_card = card
            continue

        if uname == 'NPS':
            nps_card = card
            continue

        m_fmesh = re.match(r'^FMESH(\d+)(?::([A-Za-z,]+))?$', uname)
        if m_fmesh:
            fmesh_cards[int(m_fmesh.group(1))] = card
            continue

        m_f = re.match(r'^F(\d+)(?::([A-Za-z,]+))?$', uname)
        if m_f:
            cell_tallies[int(m_f.group(1))] = card
            continue

        m_comp = re.match(r'^(FC|E|FM|SD|DE|DF|FT|FU|TF|CF|SF|FS|C|EM|TM|CM|T)(\d+)$', uname)
        if m_comp:
            t_num = int(m_comp.group(2))
            companion_cards.setdefault(t_num, []).append(card)
            continue

        if SILENT_CARD_RE.match(uname):
            continue

        unrecognized_cards.append(card)

    # 1e. Run settings: MODE
    if mode_card is not None:
        toks = mode_card["body"].split()
        settings["photon"] = any(t.upper() == 'P' for t in toks)
        unsupported_modes = [t for t in toks if t.upper() not in ('N', 'P')]
        if unsupported_modes:
            refused.append({
                "card": mode_card["name"],
                "line": mode_card["line"],
                "reason": f"particle '{unsupported_modes[0]}' isn't supported (Studio only supports neutron and photon)"
            })

    # 1e. Run settings: NPS
    if nps_card is not None:
        try:
            nps_vals = expand_shortcuts(nps_card["body"].split())
            if not nps_vals or not nps_vals[0] >= 1 or not float(nps_vals[0]).is_integer():
                raise ParseRefusal(nps_card["name"], nps_card["line"], "NPS must be a positive whole number")
            settings["nps"] = int(nps_vals[0])
        except ParseRefusal as e:
            refused.append({"card": nps_card["name"], "line": nps_card["line"], "reason": e.reason})
        except BAD_INPUT as e:
            refused.append(_unreadable(nps_card, e))

    # 1e. Run settings: KCODE & KSRC
    if kcode_card is not None:
        try:
            kc_tokens = kcode_card["body"].split()
            kc_vals = expand_shortcuts(kc_tokens)
            nsrck = int(kc_vals[0]) if len(kc_vals) > 0 else 1000
            ikz = int(kc_vals[2]) if len(kc_vals) > 2 else 30
            kct = int(kc_vals[3]) if len(kc_vals) > 3 else (ikz + 100)
            settings["runMode"] = "eigenvalue"
            settings["particles"] = nsrck
            settings["inactive"] = ikz
            settings["batches"] = kct

            if sdef_cards:
                for sc in sdef_cards:
                    refused.append({"card": sc["name"], "line": sc["line"], "reason": "KCODE runs start from KSRC"})

            # Source from KSRC or origin
            if ksrc_card is not None:
                ksrc_vals = expand_shortcuts(ksrc_card["body"].split())
                if len(ksrc_vals) < 3:
                    raise ParseRefusal(ksrc_card["name"], ksrc_card["line"], "KSRC needs x y z for at least one point")
                if len(ksrc_vals) >= 3:
                    x0, y0, z0 = ksrc_vals[0], ksrc_vals[1], ksrc_vals[2]
                    n_pts = len(ksrc_vals) // 3
                    if n_pts > 1:
                        notes.append(f"KSRC gave {n_pts} points; Studio eigenvalue runs start from one point")
                    sources.append({
                        "name": "Source (from the deck)", "particle": "neutron", "strength": 1,
                        "space": "point", "x": x0, "y": y0, "z": z0,
                        "angle": "isotropic", "energy": "watt", "wa": 0.988, "wb": 2.249
                    })
            else:
                notes.append("KCODE without KSRC: point source placed at origin")
                sources.append({
                    "name": "Source (from the deck)", "particle": "neutron", "strength": 1,
                    "space": "point", "x": 0.0, "y": 0.0, "z": 0.0,
                    "angle": "isotropic", "energy": "watt", "wa": 0.988, "wb": 2.249
                })
        except ParseRefusal as e:
            refused.append({"card": e.card or kcode_card["name"], "line": e.line or kcode_card["line"], "reason": e.reason})
        except BAD_INPUT as e:
            refused.append(_unreadable(kcode_card, e))

    # 1d. Source: SDEF
    dists_used = set()
    if kcode_card is None:
        if len(sdef_cards) > 1:
            # Second SDEF -> refuse whole source
            refused.append({"card": sdef_cards[1]["name"], "line": sdef_cards[1]["line"], "reason": "a second SDEF card is not supported"})
        elif len(sdef_cards) == 1:
            sc = sdef_cards[0]
            try:
                src, used = _parse_sdef(sc, si_cards, sp_cards, sb_cards, ds_cards, notes)
                sources.append(src)
                dists_used.update(used)
            except ParseRefusal as e:
                refused.append({"card": e.card or sc["name"], "line": e.line or sc["line"], "reason": e.reason})
            except BAD_INPUT as e:
                refused.append(_unreadable(sc, e))

    # 1f. Cell tallies
    for t_num, card in cell_tallies.items():
        comps = companion_cards.get(t_num, [])
        if t_num % 10 != 4:
            refused.append({"card": card["name"], "line": card["line"], "reason": "F1/F2/F5/... tallies aren't imported"})
            continue
        try:
            tally = _parse_cell_tally(card, comps, notes)
            tallies.append(tally)
        except ParseRefusal as e:
            refused.append({"card": card["name"], "line": card["line"], "reason": e.reason})
        except BAD_INPUT as e:
            refused.append(_unreadable(card, e))

    # 1g. Mesh tallies
    for t_num, card in fmesh_cards.items():
        comps = companion_cards.get(t_num, [])
        try:
            tally = _parse_mesh_tally(card, comps)
            tallies.append(tally)
        except ParseRefusal as e:
            refused.append({"card": card["name"], "line": card["line"], "reason": e.reason})
        except BAD_INPUT as e:
            refused.append(_unreadable(card, e))

    # Orphan companion cards (not associated with any cell tally or mesh tally)
    known_tallies = set(cell_tallies.keys()) | set(fmesh_cards.keys())
    for t_num, comps in companion_cards.items():
        if t_num not in known_tallies:
            for c in comps:
                unrecognized_cards.append(c)

    # Orphan SI / SP cards (not used by SDEF)
    if kcode_card is None and sdef_cards:
        for num, c in si_cards.items():
            if num not in dists_used:
                unrecognized_cards.append(c)
        for num, c in sp_cards.items():
            if num not in dists_used:
                unrecognized_cards.append(c)
    else:
        for c in si_cards.values():
            unrecognized_cards.append(c)
        for c in sp_cards.values():
            unrecognized_cards.append(c)

    # Orphan SB / DS cards
    for c in sb_cards.values():
        unrecognized_cards.append(c)
    for c in ds_cards.values():
        unrecognized_cards.append(c)

    # Orphan KSRC
    if kcode_card is None and ksrc_card is not None:
        unrecognized_cards.append(ksrc_card)

    # 1c. Every other card not listed goes to refused
    for c in unrecognized_cards:
        refused.append({
            "card": c["name"],
            "line": c["line"],
            "reason": "not imported (Studio has no equivalent yet)"
        })

    # Sort refused by line number
    refused.sort(key=lambda r: r["line"])

    return {
        "sources": sources,
        "tallies": tallies,
        "settings": settings,
        "refused": refused,
        "notes": notes,
    }


def _parse_sdef(card, si_cards, sp_cards, sb_cards, ds_cards, notes):
    """Parse one SDEF card. Returns (source_dict, set_of_used_dist_ints)."""
    pairs = _parse_key_values(card["body"], ALLOWED_SDEF_KEYS, special_values={'N', 'P', '1', '2'})
    for k in pairs:
        if k not in ALLOWED_SDEF_KEYS:
            raise ParseRefusal(card["name"], card["line"], f"SDEF keyword '{k}' isn't supported")

    dists_used = set()

    def check_dist_cards(d_num):
        if d_num in sb_cards:
            raise ParseRefusal(card["name"], card["line"], f"card SB{d_num} isn't supported")
        if d_num in ds_cards:
            raise ParseRefusal(card["name"], card["line"], f"card DS{d_num} isn't supported")

    # WGT
    if 'WGT' in pairs:
        w_tokens = pairs['WGT']
        try:
            w_vals = expand_shortcuts(w_tokens)
            if not (len(w_vals) == 1 and abs(w_vals[0] - 1.0) < 1e-9):
                raise ParseRefusal(card["name"], card["line"], "WGT must equal 1")
        except ParseRefusal:
            raise
        except Exception:
            raise ParseRefusal(card["name"], card["line"], "WGT must equal 1")

    # Particle
    particle = "neutron"
    if 'PAR' in pairs:
        p_toks = pairs['PAR']
        if not p_toks:
            particle = "neutron"
        else:
            p_val = p_toks[0].upper()
            if p_val in ('1', 'N'):
                particle = "neutron"
            elif p_val in ('2', 'P'):
                particle = "photon"
            else:
                raise ParseRefusal(card["name"], card["line"], f"particle '{p_toks[0]}' isn't supported")

    src = {
        "name": "Source (from the deck)",
        "particle": particle,
        "strength": 1
    }

    # POS
    pos = [0.0, 0.0, 0.0]
    if 'POS' in pairs:
        pos_toks = pairs['POS']
        if pos_toks and re.match(r'^[dD]\d+$', pos_toks[0]):
            raise ParseRefusal(card["name"], card["line"], "distribution for POS isn't supported")
        try:
            pos_vals = expand_shortcuts(pos_toks)
            if len(pos_vals) == 3:
                pos = [float(pos_vals[0]), float(pos_vals[1]), float(pos_vals[2])]
            else:
                raise ParseRefusal(card["name"], card["line"], "POS requires 3 numbers")
        except ParseRefusal:
            raise
        except Exception as e:
            raise ParseRefusal(card["name"], card["line"], f"POS error: {e}")

    # Space
    has_x = 'X' in pairs
    has_y = 'Y' in pairs
    has_z = 'Z' in pairs
    has_rad = 'RAD' in pairs
    has_ext = 'EXT' in pairs
    has_axs = 'AXS' in pairs

    if has_x or has_y or has_z:
        if not (has_x and has_y and has_z and not has_rad and not has_ext and not has_axs):
            raise ParseRefusal(card["name"], card["line"], "box source requires X, Y, Z distributions")

        def parse_box_dim(dim_toks):
            if not (len(dim_toks) == 1 and re.match(r'^[dD]\d+$', dim_toks[0])):
                raise ParseRefusal(card["name"], card["line"], "box source requires D<n> for X, Y, Z")
            d_num = int(dim_toks[0][1:])
            dists_used.add(d_num)
            check_dist_cards(d_num)
            if d_num not in si_cards or d_num not in sp_cards:
                raise ParseRefusal(card["name"], card["line"], f"missing SI{d_num} or SP{d_num} for box distribution")

            # Check SI
            si_body = si_cards[d_num]["body"].split()
            if si_body and si_body[0].upper() == 'S':
                raise ParseRefusal(card["name"], card["line"], f"SI{d_num} with option S (several sources) isn't supported")
            if si_body and si_body[0].upper() == 'H':
                si_body = si_body[1:]
            si_vals = expand_shortcuts(si_body)
            if len(si_vals) != 2:
                raise ParseRefusal(card["name"], card["line"], f"SI{d_num} for box dimension must have 2 values")

            # Check SP: 0 1 or D 0 1
            sp_body = sp_cards[d_num]["body"].split()
            if sp_body and sp_body[0].upper() == 'D':
                sp_body = sp_body[1:]
            sp_vals = expand_shortcuts(sp_body)
            if not (len(sp_vals) == 2 and abs(sp_vals[0]) < 1e-9 and abs(sp_vals[1] - 1.0) < 1e-9):
                raise ParseRefusal(card["name"], card["line"], f"SP{d_num} for box dimension must equal 0 1")

            return min(si_vals[0], si_vals[1]), max(si_vals[0], si_vals[1])

        x0, x1 = parse_box_dim(pairs['X'])
        y0, y1 = parse_box_dim(pairs['Y'])
        z0, z1 = parse_box_dim(pairs['Z'])
        src["space"] = "box"
        src["x0"], src["x1"] = x0, x1
        src["y0"], src["y1"] = y0, y1
        src["z0"], src["z1"] = z0, z1

    elif has_rad and not has_axs and not has_ext:
        rad_toks = pairs['RAD']
        if not (len(rad_toks) == 1 and re.match(r'^[dD]\d+$', rad_toks[0])):
            raise ParseRefusal(card["name"], card["line"], "sphere source requires RAD=D<n>")
        d_num = int(rad_toks[0][1:])
        dists_used.add(d_num)
        check_dist_cards(d_num)
        if d_num not in si_cards or d_num not in sp_cards:
            raise ParseRefusal(card["name"], card["line"], f"missing SI{d_num} or SP{d_num} for sphere radius")

        si_body = si_cards[d_num]["body"].split()
        if si_body and si_body[0].upper() == 'S':
            raise ParseRefusal(card["name"], card["line"], f"SI{d_num} with option S isn't supported")
        si_vals = expand_shortcuts(si_body)
        if len(si_vals) == 1:
            rin, r = 0.0, float(si_vals[0])
        elif len(si_vals) == 2:
            rin, r = float(si_vals[0]), float(si_vals[1])
        else:
            raise ParseRefusal(card["name"], card["line"], f"SI{d_num} for sphere radius must have 1 or 2 values")

        sp_body = sp_cards[d_num]["body"].split()
        sp_vals = expand_shortcuts(sp_body)
        if not (len(sp_vals) == 2 and abs(sp_vals[0] - (-21)) < 1e-9 and abs(sp_vals[1] - 2) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], f"SP{d_num} for sphere must be -21 2")

        src["space"] = "sphere"
        src["x"], src["y"], src["z"] = pos[0], pos[1], pos[2]
        src["rin"], src["r"] = rin, r

    elif has_axs and has_rad and has_ext:
        axs_vals = expand_shortcuts(pairs['AXS'])
        if not (len(axs_vals) == 3 and abs(axs_vals[0]) < 1e-9 and abs(axs_vals[1]) < 1e-9 and abs(axs_vals[2] - 1.0) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], "cylinder source AXS must be 0 0 1")

        rad_toks = pairs['RAD']
        if not (len(rad_toks) == 1 and re.match(r'^[dD]\d+$', rad_toks[0])):
            raise ParseRefusal(card["name"], card["line"], "cylinder source requires RAD=D<n>")
        d_rad = int(rad_toks[0][1:])
        dists_used.add(d_rad)
        check_dist_cards(d_rad)
        if d_rad not in si_cards or d_rad not in sp_cards:
            raise ParseRefusal(card["name"], card["line"], f"missing SI{d_rad} or SP{d_rad} for cylinder radius")

        si_rad_body = si_cards[d_rad]["body"].split()
        if si_rad_body and si_rad_body[0].upper() == 'S':
            raise ParseRefusal(card["name"], card["line"], f"SI{d_rad} with option S isn't supported")
        si_rad_vals = expand_shortcuts(si_rad_body)
        if len(si_rad_vals) == 1:
            rin, r = 0.0, float(si_rad_vals[0])
        elif len(si_rad_vals) == 2:
            rin, r = float(si_rad_vals[0]), float(si_rad_vals[1])
        else:
            raise ParseRefusal(card["name"], card["line"], f"SI{d_rad} for cylinder radius must have 1 or 2 values")

        sp_rad_vals = expand_shortcuts(sp_cards[d_rad]["body"].split())
        if not (len(sp_rad_vals) == 2 and abs(sp_rad_vals[0] - (-21)) < 1e-9 and abs(sp_rad_vals[1] - 1) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], f"SP{d_rad} for cylinder must be -21 1")

        ext_toks = pairs['EXT']
        if not (len(ext_toks) == 1 and re.match(r'^[dD]\d+$', ext_toks[0])):
            raise ParseRefusal(card["name"], card["line"], "cylinder source requires EXT=D<m>")
        d_ext = int(ext_toks[0][1:])
        dists_used.add(d_ext)
        check_dist_cards(d_ext)
        if d_ext not in si_cards or d_ext not in sp_cards:
            raise ParseRefusal(card["name"], card["line"], f"missing SI{d_ext} or SP{d_ext} for cylinder ext")

        si_ext_body = si_cards[d_ext]["body"].split()
        if si_ext_body and si_ext_body[0].upper() == 'S':
            raise ParseRefusal(card["name"], card["line"], f"SI{d_ext} with option S isn't supported")
        si_ext_vals = expand_shortcuts(si_ext_body)
        if len(si_ext_vals) != 2:
            raise ParseRefusal(card["name"], card["line"], f"SI{d_ext} for cylinder EXT must have 2 values")

        sp_ext_vals = expand_shortcuts(sp_cards[d_ext]["body"].split())
        if not (len(sp_ext_vals) == 2 and abs(sp_ext_vals[0] - (-21)) < 1e-9 and abs(sp_ext_vals[1] - 0) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], f"SP{d_ext} for cylinder EXT must be -21 0")

        ea, eb = si_ext_vals[0], si_ext_vals[1]
        src["space"] = "cylinder"
        src["x"], src["y"] = pos[0], pos[1]
        src["z"] = pos[2] + (ea + eb) / 2.0
        src["h"] = eb - ea
        src["rin"], src["r"] = rin, r

    elif not has_x and not has_y and not has_z and not has_rad and not has_ext and not has_axs:
        src["space"] = "point"
        src["x"], src["y"], src["z"] = pos[0], pos[1], pos[2]
    else:
        raise ParseRefusal(card["name"], card["line"], "spatial definition in SDEF isn't supported")

    # Direction
    has_dir = 'DIR' in pairs
    has_vec = 'VEC' in pairs
    if not has_dir and not has_vec:
        src["angle"] = "isotropic"
    elif has_dir and has_vec:
        dir_vals = expand_shortcuts(pairs['DIR'])
        if not (len(dir_vals) == 1 and abs(dir_vals[0] - 1.0) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], "DIR must equal 1 for mono-directional beam")
        vec_vals = expand_shortcuts(pairs['VEC'])
        if len(vec_vals) != 3:
            raise ParseRefusal(card["name"], card["line"], "VEC requires 3 components")
        u, v, w = vec_vals[0], vec_vals[1], vec_vals[2]
        norm = math.sqrt(u * u + v * v + w * w)
        if norm <= 1e-12:
            raise ParseRefusal(card["name"], card["line"], "VEC cannot be 0, 0, 0")
        src["angle"] = "mono"
        src["u"] = u / norm
        src["v"] = v / norm
        src["w"] = w / norm
    else:
        raise ParseRefusal(card["name"], card["line"], "directional definition in SDEF isn't supported")

    # Energy
    if 'ERG' not in pairs:
        src["energy"] = "lines"
        src["lines"] = "14:1"
        notes.append("ERG missing: MCNP's default 14 MeV")
    else:
        erg_toks = pairs['ERG']
        if not erg_toks:
            src["energy"] = "lines"
            src["lines"] = "14:1"
            notes.append("ERG missing: MCNP's default 14 MeV")
        elif len(erg_toks) == 1 and not re.match(r'^[dD]\d+$', erg_toks[0]):
            e_vals = expand_shortcuts(erg_toks)
            src["energy"] = "lines"
            src["lines"] = f"{fmt_num(e_vals[0])}:1"
        elif len(erg_toks) == 1 and re.match(r'^[dD]\d+$', erg_toks[0]):
            d_num = int(erg_toks[0][1:])
            dists_used.add(d_num)
            check_dist_cards(d_num)
            if d_num not in sp_cards:
                raise ParseRefusal(card["name"], card["line"], f"missing SP{d_num} for ERG distribution")

            sp_raw = sp_cards[d_num]["body"].split()
            # Check SP options C or V
            if sp_raw and sp_raw[0].upper() in ('C', 'V'):
                raise ParseRefusal(card["name"], card["line"], f"SP{d_num} option {sp_raw[0].upper()} isn't supported")

            if not sp_raw:
                raise ParseRefusal(card["name"], card["line"], f"SP{d_num} has no values")

            # Check negative functions. A leading D (the default option) is followed by
            # probabilities; any other first entry must be a number.
            first_sp_num = None
            if sp_raw[0].upper() != 'D':
                try:
                    first_sp_num = float(sp_raw[0].replace('D', 'E').replace('d', 'e'))
                except ValueError:
                    raise ParseRefusal(card["name"], card["line"], f"SP{d_num} value '{sp_raw[0]}' isn't a number")

            if first_sp_num is not None and first_sp_num < 0:
                fn = int(first_sp_num)
                sp_vals = expand_shortcuts(sp_raw)
                if fn == -3 and len(sp_vals) >= 3:
                    src["energy"] = "watt"
                    src["wa"] = sp_vals[1]
                    src["wb"] = sp_vals[2]
                elif fn == -2 and len(sp_vals) >= 2:
                    src["energy"] = "maxwell"
                    src["theta"] = sp_vals[1]
                elif fn == -4 and len(sp_vals) >= 3:
                    a = sp_vals[1]
                    b = sp_vals[2]
                    mrat = 4.0 if abs(b - 2.45) < 0.1 else 5.0
                    kt = a * a * mrat / (4.0 * b) * 1e6
                    src["energy"] = "muir"
                    src["muir_e0"] = b
                    src["muir_mrat"] = mrat
                    src["muir_kt"] = kt
                else:
                    raise ParseRefusal(card["name"], card["line"], f"SP{d_num} negative function number isn't supported")
            else:
                # Distribution with SI
                if d_num not in si_cards:
                    raise ParseRefusal(card["name"], card["line"], f"missing SI{d_num} for ERG distribution")
                si_raw = si_cards[d_num]["body"].split()
                opt = 'H'
                if si_raw and si_raw[0].upper() in ('H', 'L', 'S'):
                    opt = si_raw[0].upper()
                    si_raw = si_raw[1:]
                if opt == 'S':
                    raise ParseRefusal(card["name"], card["line"], f"SI{d_num} with option S (several sources) isn't supported")

                si_vals = expand_shortcuts(si_raw)

                sp_toks = sp_cards[d_num]["body"].split()
                if sp_toks and sp_toks[0].upper() == 'D':
                    sp_toks = sp_toks[1:]
                sp_vals = expand_shortcuts(sp_toks)

                if opt == 'L':
                    if len(si_vals) != len(sp_vals):
                        raise ParseRefusal(card["name"], card["line"], f"SI{d_num} and SP{d_num} length mismatch for discrete lines")
                    src["energy"] = "lines"
                    src["lines"] = ", ".join(f"{fmt_num(e)}:{fmt_num(p)}" for e, p in zip(si_vals, sp_vals))
                else:
                    # Histogram
                    if not sp_vals or abs(sp_vals[0]) > 1e-12:
                        raise ParseRefusal(card["name"], card["line"], "the first histogram entry must be 0")
                    probs = sp_vals[1:]
                    k = len(si_vals) - 1
                    if len(probs) != k:
                        raise ParseRefusal(card["name"], card["line"], f"SI{d_num} edges ({len(si_vals)}) and SP{d_num} bins ({len(probs)}) mismatch")
                    if k == 1 and probs[0] > 0:
                        src["energy"] = "uniform"
                        src["emin"] = si_vals[0]
                        src["emax"] = si_vals[1]
                    else:
                        src["energy"] = "tabulated"
                        src["tab_e"] = ", ".join(fmt_num(e) for e in si_vals)
                        src["tab_p"] = ", ".join(fmt_num(p) for p in probs)
        else:
            raise ParseRefusal(card["name"], card["line"], "ERG syntax isn't supported")

    return src, dists_used


def _parse_cell_tally(card, comps, notes):
    """Parse one F<n> cell tally and its companion cards."""
    uname = card["name"].upper()
    m_f = re.match(r'^F(\d+)(?::([A-Za-z,]+))?$', uname)
    t_num = int(m_f.group(1))
    part_token = m_f.group(2)

    particle = "neutron"
    if part_token:
        p_up = part_token.upper()
        if p_up == 'N':
            particle = "neutron"
        elif p_up == 'P':
            particle = "photon"
        else:
            raise ParseRefusal(card["name"], card["line"], f"tally {uname} particle isn't supported")

    # Check companion cards for unsupported cards
    unsupported_comp_re = re.compile(r'^(DE|DF|FT|FU|TF|CF|SF|FS|C|EM|TM|CM|T)\d+$', re.IGNORECASE)
    for c in comps:
        if unsupported_comp_re.match(c["name"]):
            raise ParseRefusal(card["name"], card["line"], f"{c['name']} cards aren't imported")

    # Bins: plain positive integers only
    body_toks = card["body"].split()
    cells_mcnp = []
    for tok in body_toks:
        if not re.match(r'^\d+$', tok) or int(tok) <= 0:
            raise ParseRefusal(card["name"], card["line"], "tally bins must be plain positive integers")
        cells_mcnp.append(int(tok))

    if not cells_mcnp:
        raise ParseRefusal(card["name"], card["line"], "tally must list at least one cell")

    # Name from FC<n>
    name = f"F{t_num}"
    for c in comps:
        if re.match(r'^FC\d+$', c["name"], re.IGNORECASE):
            name = c["body"].strip()
            break

    # E<n>
    ebins = ""
    for c in comps:
        if re.match(r'^E\d+$', c["name"], re.IGNORECASE):
            e_toks = c["body"].split()
            if any(t.upper() in ('NT', 'C') for t in e_toks):
                raise ParseRefusal(card["name"], card["line"], f"E{t_num} with option NT/C isn't supported")
            e_vals = expand_shortcuts(e_toks)
            ebins = "0, " + ", ".join(fmt_num(e) for e in e_vals)
            break

    # FM<n>
    scores = ["flux"]
    fm_material = None
    for c in comps:
        if re.match(r'^FM\d+$', c["name"], re.IGNORECASE):
            raw = c["body"].replace('(', ' ').replace(')', ' ').split()
            if len(raw) >= 3:
                first_tok = raw[0].replace('D', 'E').replace('d', 'e')
                try:
                    first_val = float(first_tok)
                except Exception:
                    first_val = 0.0
                if abs(first_val - (-1.0)) < 1e-9:
                    try:
                        m_id = int(raw[1])
                    except Exception:
                        raise ParseRefusal(card["name"], card["line"], f"invalid FM{t_num} material")
                    reactions = raw[2:]
                    reaction_str = " ".join(reactions)
                    rx_map = {
                        "-1": "total",
                        "-2": "absorption",
                        "-6": "fission",
                        "-6 -7": "nu-fission",
                        "102": "(n,gamma)",
                        "103": "(n,p)",
                        "107": "(n,a)"
                    }
                    if reaction_str in rx_map:
                        scores = [rx_map[reaction_str]]
                        fm_material = m_id
                    else:
                        raise ParseRefusal(card["name"], card["line"], f"FM{t_num} reaction {reaction_str} isn't supported")
                else:
                    raise ParseRefusal(card["name"], card["line"], f"FM{t_num} multiplier isn't supported")
            else:
                raise ParseRefusal(card["name"], card["line"], f"FM{t_num} syntax isn't supported")
            break

    # SD<n>
    sd_found = False
    for c in comps:
        if re.match(r'^SD\d+$', c["name"], re.IGNORECASE):
            sd_found = True
            sd_vals = expand_shortcuts(c["body"].split())
            if not all(abs(v - 1.0) < 1e-9 for v in sd_vals):
                notes.append(f"F{t_num}: SD values ignored")
            break
    if not sd_found:
        notes.append(f"F{t_num}: MCNP divides by the cell volume; Studio's cell tallies are integrated over the cell (like SD 1)")

    out = {
        "kind": "cell",
        "cells_mcnp": cells_mcnp,
        "particle": particle,
        "scores": scores,
        "ebins": ebins,
        "name": name,
        "mcnp_card": card["name"]
    }
    if fm_material is not None:
        out["fm_material"] = fm_material
    return out


def _parse_mesh_tally(card, comps):
    """Parse one FMESH<n> mesh tally."""
    uname = card["name"].upper()
    m_fmesh = re.match(r'^FMESH(\d+)(?::([A-Za-z,]+))?$', uname)
    t_num = int(m_fmesh.group(1))
    part_token = m_fmesh.group(2)

    particle = "neutron"
    if part_token:
        p_up = part_token.upper()
        if p_up == 'N':
            particle = "neutron"
        elif p_up == 'P':
            particle = "photon"
        else:
            raise ParseRefusal(card["name"], card["line"], f"mesh tally {uname} particle isn't supported")

    # Companion cards for FMESH -> refuse
    if comps:
        raise ParseRefusal(card["name"], card["line"], f"companion cards for {card['name']} aren't supported")

    pairs = _parse_key_values(card["body"], ALLOWED_FMESH_KEYS, special_values={'XYZ', 'CYL'})
    for k in pairs:
        if k not in ALLOWED_FMESH_KEYS:
            raise ParseRefusal(card["name"], card["line"], f"FMESH keyword '{k}' isn't supported")

    geom = "XYZ"
    if 'GEOM' in pairs and pairs['GEOM']:
        geom = pairs['GEOM'][0].upper()
    if geom not in ('XYZ', 'CYL'):
        raise ParseRefusal(card["name"], card["line"], f"FMESH GEOM '{geom}' isn't supported")

    # ORIGIN
    origin = [0.0, 0.0, 0.0]
    if 'ORIGIN' in pairs:
        o_vals = expand_shortcuts(pairs['ORIGIN'])
        if len(o_vals) == 3:
            origin = [float(o_vals[0]), float(o_vals[1]), float(o_vals[2])]
        else:
            raise ParseRefusal(card["name"], card["line"], "FMESH ORIGIN requires 3 coordinates")

    # EMESH & EINTS
    ebins = ""
    if 'EMESH' in pairs:
        e_vals = expand_shortcuts(pairs['EMESH'])
        if 'EINTS' in pairs:
            eints_vals = expand_shortcuts(pairs['EINTS'])
            if not all(abs(v - 1.0) < 1e-9 for v in eints_vals):
                raise ParseRefusal(card["name"], card["line"], "FMESH EINTS values must be 1")
        ebins = "0, " + ", ".join(fmt_num(e) for e in e_vals)

    def expand_fine_mesh(coord0, mesh_toks, ints_toks):
        if not mesh_toks:
            raise ParseRefusal(card["name"], card["line"], "FMESH missing mesh boundaries")
        coarse = expand_shortcuts(mesh_toks)
        ints = expand_shortcuts(ints_toks) if ints_toks else []
        if len(ints) < len(coarse):
            ints.extend([10] * (len(coarse) - len(ints)))
        fine = [coord0]
        cur = coord0
        for b, count in zip(coarse, ints):
            n = int(count)
            step = (b - cur) / n
            for j in range(1, n):
                fine.append(cur + j * step)
            fine.append(b)
            cur = b
        # Check uniformity
        first_e = coord0
        last_e = coarse[-1]
        total_bins = len(fine) - 1
        span = last_e - first_e
        fine_step = span / total_bins
        tol = 1e-9 * max(1.0, abs(span))
        for idx_e, val_e in enumerate(fine):
            exp_e = first_e + idx_e * fine_step
            if abs(val_e - exp_e) > tol:
                raise ParseRefusal(card["name"], card["line"], "Studio mesh bins are uniform")
        return total_bins, first_e, last_e

    if geom == 'XYZ':
        nx, lx, ux = expand_fine_mesh(origin[0], pairs.get('IMESH', []), pairs.get('IINTS', []))
        ny, ly, uy = expand_fine_mesh(origin[1], pairs.get('JMESH', []), pairs.get('JINTS', []))
        nz, lz, uz = expand_fine_mesh(origin[2], pairs.get('KMESH', []), pairs.get('KINTS', []))
        return {
            "kind": "mesh",
            "nx": nx, "ny": ny, "nz": nz,
            "lx": lx, "ly": ly, "lz": lz,
            "ux": ux, "uy": uy, "uz": uz,
            "particle": particle,
            "scores": ["flux"],
            "ebins": ebins,
            "name": f"FMESH{t_num}"
        }
    else:  # CYL
        # AXS: default 0 0 1
        axs = [0.0, 0.0, 1.0]
        if 'AXS' in pairs:
            axs_vals = expand_shortcuts(pairs['AXS'])
            if len(axs_vals) == 3:
                axs = axs_vals
        if not (abs(axs[0]) < 1e-9 and abs(axs[1]) < 1e-9 and abs(axs[2] - 1.0) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], "cylindrical FMESH requires AXS=0 0 1")

        # VEC: default 1 0 0
        vec = [1.0, 0.0, 0.0]
        if 'VEC' in pairs:
            vec_vals = expand_shortcuts(pairs['VEC'])
            if len(vec_vals) == 3:
                vec = vec_vals
        if not (abs(vec[0] - 1.0) < 1e-9 and abs(vec[1]) < 1e-9 and abs(vec[2]) < 1e-9):
            raise ParseRefusal(card["name"], card["line"], "cylindrical FMESH requires VEC=1 0 0")

        nr, rmin, rmax = expand_fine_mesh(0.0, pairs.get('IMESH', []), pairs.get('IINTS', []))
        # JMESH heights are measured from ORIGIN along AXS, like Studio's z grid.
        nz, zmin, zmax = expand_fine_mesh(0.0, pairs.get('JMESH', []), pairs.get('JINTS', []))
        nphi, kmin, kmax = expand_fine_mesh(0.0, pairs.get('KMESH', []), pairs.get('KINTS', []))
        if kmax > 1.0 + 1e-9:
            raise ParseRefusal(card["name"], card["line"], "cylindrical FMESH K revolution must be <= 1")
        phimax = kmax * 2.0 * math.pi

        return {
            "kind": "mesh",
            "meshGeom": "cylindrical",
            "nr": nr, "rmin": 0.0, "rmax": rmax,
            "nz": nz, "zmin": zmin, "zmax": zmax,
            "nphi": nphi, "phimin": 0.0, "phimax": phimax,
            "ox": origin[0], "oy": origin[1], "oz": origin[2],
            "particle": particle,
            "scores": ["flux"],
            "ebins": ebins,
            "name": f"FMESH{t_num}"
        }
