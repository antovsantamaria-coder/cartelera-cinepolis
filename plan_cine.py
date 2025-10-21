""""
Planificador de funciones de cine con restricciones específicas.

Entrada: CSV con columnas
- sala (str)
- titulo (str)
- genero (str)              -> "terror", "romántica"/"romance", u otro
- duracion_min (int)
- clasificacion (str)
- funcion (int, opcional)

Restricciones:
- Inicios desde 10:40 (inclusive) y hasta 22:40 (inclusive).
- Ninguna función termina después de 00:50.
- No se cambia la sala indicada.
- Eliminar la 5ª función de Harry Potter.
- Fijar UNA función de Harry Potter a las 11:00.
- Terror: inicio >= 13:00.
- Románticas: tope de inicio 21:30.
- No pueden iniciar dos películas a la misma hora (global).
- Mismo título: separación mínima de 30 min entre inicios.
- Grilla de 5 min con heurística de “equidistancia”.

Uso:
    python plan_cine.py --input peliculas.csv --output plan.csv
"""
import argparse, csv
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Set

GRID_MIN = 5
EARLIEST_START = 10*60 + 40
LATEST_START   = 22*60 + 40
LATEST_END     = 24*60 + 50
TERROR_MIN_START = 13*60
ROMANCE_MAX_START = 21*60 + 30
SAME_TITLE_MIN_GAP = 30

@dataclass
class Screening:
    idx: int
    sala: str
    titulo: str
    genero: str
    duracion: int
    clasificacion: str
    funcion: Optional[int] = None
    forced_start: Optional[int] = None

def parse_csv(path: str) -> List["Screening"]:
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        required = {'sala','titulo','genero','duracion_min'}
        if not required.issubset(set([c.strip() for c in reader.fieldnames])):
            raise ValueError(f"El CSV debe tener columnas {required}. Encontradas: {reader.fieldnames}")
        for i, row in enumerate(reader):
            sala = row['sala'].strip()
            titulo = row['titulo'].strip()
            genero = row['genero'].strip().lower()
            dur = int(row['duracion_min'])
            clasif = row.get('clasificacion','').strip()
            func = row.get('funcion', '').strip()
            funcion = int(func) if func.isdigit() else None
            rows.append(Screening(i, sala, titulo, genero, dur, clasif, funcion))
    return rows

def minutes_to_hhmm(m: int) -> str:
    if m < 24*60:
        h = m // 60; mm = m % 60
        return f"{h:02d}:{mm:02d}"
    m2 = m - 24*60
    h = m2 // 60; mm = m2 % 60
    return f"{h:02d}:{mm:02d}+1d"

def remove_hp_5th(screenings: List["Screening"]) -> List["Screening"]:
    hp_indices = [i for i, s in enumerate(screenings) if 'harry potter' in s.titulo.lower()]
    if not hp_indices:
        return screenings
    for i, s in enumerate(screenings):
        if 'harry potter' in s.titulo.lower() and s.funcion == 5:
            return [x for j, x in enumerate(screenings) if j != i]
    if len(hp_indices) >= 5:
        drop_idx = hp_indices[4]
        return [x for j, x in enumerate(screenings) if j != drop_idx]
    return screenings

def force_one_hp_at_11(screenings: List["Screening"]) -> None:
    hp = [s for s in screenings if 'harry potter' in s.titulo.lower()]
    if not hp:
        return
    hp_with_func = [s for s in hp if s.funcion is not None]
    chosen = sorted(hp_with_func, key=lambda s: s.funcion)[0] if hp_with_func else sorted(hp, key=lambda s: s.idx)[0]
    chosen.forced_start = 11*60

def feasible_starts_for(s: "Screening") -> List[int]:
    start_lo = EARLIEST_START
    start_hi = LATEST_START
    if s.genero == 'terror':
        start_lo = max(start_lo, TERROR_MIN_START)
    if s.genero in ('romance','romántica','romantica'):
        start_hi = min(start_hi, ROMANCE_MAX_START)
    if s.forced_start is not None:
        start_lo = max(start_lo, s.forced_start)
        start_hi = min(start_hi, s.forced_start)
    starts = []
    t = start_lo - (start_lo % GRID_MIN)
    if t < start_lo: t += GRID_MIN
    while t <= start_hi:
        end = t + s.duracion
        if end <= LATEST_END:
            starts.append(t)
        t += GRID_MIN
    return starts

def intervals_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return not (a_end <= b_start or b_end <= a_start)

def backtrack_assign(screenings: List["Screening"]) -> Optional[Dict[int, int]]:
    candidates: Dict[int, List[int]] = {s.idx: feasible_starts_for(s) for s in screenings}
    order = sorted(screenings, key=lambda s: (len(candidates[s.idx]), -s.duracion))
    assigned: Dict[int, int] = {}
    hall_intervals: Dict[str, List[Tuple[int,int]]] = defaultdict(list)
    title_starts: Dict[str, List[int]] = defaultdict(list)
    used_starts: Set[int] = set()

    def is_ok(s: "Screening", t: int) -> bool:
        end = t + s.duracion
        for (a, b) in hall_intervals[s.sala]:
            if intervals_overlap(t, end, a, b):
                return False
        if t in used_starts:
            return False
        for ts in title_starts[s.titulo.lower()]:
            if abs(t - ts) < SAME_TITLE_MIN_GAP:
                return False
        return True

    def score_start(t: int) -> float:
        if not used_starts:
            return 0.0
        nearest = min(abs(t - u) for u in used_starts)
        return -nearest

    def dfs(i: int) -> bool:
        if i == len(order):
            return True
        s = order[i]
        cands = candidates[s.idx]
        if not cands:
            return False
        for t in sorted(cands, key=score_start):
            if is_ok(s, t):
                assigned[s.idx] = t
                hall_intervals[s.sala].append((t, t + s.duracion))
                hall_intervals[s.sala].sort()
                title_starts[s.titulo.lower()].append(t)
                title_starts[s.titulo.lower()].sort()
                used_starts.add(t)
                if dfs(i+1):
                    return True
                used_starts.remove(t)
                title_starts[s.titulo.lower()].remove(t)
                hall_intervals[s.sala].remove((t, t + s.duracion))
                del assigned[s.idx]
        return False

    ok = dfs(0)
    return assigned if ok else None

def planificar(path_in: str, path_out: str) -> None:
    screenings = parse_csv(path_in)
    screenings = remove_hp_5th(screenings)
    force_one_hp_at_11(screenings)
    assignment = backtrack_assign(screenings)
    if assignment is None:
        raise RuntimeError("No se encontró una planificación que cumpla todas las restricciones.")
    rows = []
    for s in screenings:
        start = assignment[s.idx]; end = start + s.duracion
        rows.append({
            "sala": s.sala,
            "titulo": s.titulo,
            "genero": s.genero,
            "clasificacion": s.clasificacion,
            "duracion_min": s.duracion,
            "inicio": minutes_to_hhmm(start),
            "termino": minutes_to_hhmm(end),
        })
    rows.sort(key=lambda r: (r["inicio"], r["sala"]))
    with open(path_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description="Planificador de funciones de cine")
    ap.add_argument("--input", required=True, help="Ruta al CSV de entrada")
    ap.add_argument("--output", default="planificacion_resultado.csv", help="Ruta al CSV de salida")
    args = ap.parse_args()
    planificar(args.input, args.output)
    print(f"Planificación escrita en {args.output}")

if __name__ == "__main__":
    main()