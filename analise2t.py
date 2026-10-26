#!/usr/bin/env python3
"""Painel do DJ — coleta para a análise do 2º turno 2026 (DAKIA).
Baixa do TSE, município a município, o 1º e o 2º turno de 2026 (votos de todos os candidatos,
comparecimento, abstenção, brancos e nulos), junta com 2022 (cache do painel) e publica no
Supabase do painel, um pacote por estado (ids 'an:uf'). Não mexe no servidor2.py que está rodando.
Uso (na pasta do painel):  python3 analise2t.py
"""
import json, os, ssl, sys, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "dados_apuracao")
RAIZ = "https://resultados.tse.jus.br/oficial/ele2026"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa",
       "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]
SUPA_URL = "https://ihwdycrujrvpwvjfcioy.supabase.co"
SUPA_KEY = "sb_publishable_-fE5D8rarCcGXt1FHHf5TA_SRIOZ483"
SUPA_TOKEN = "a453b36a4d9520971abce1f32cfe31cc1eeb"
H = {"User-Agent": "PainelApuracaoPessoal/2.0-analise", "Accept-Encoding": "identity"}

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()
CTX_TSE = [CTX]


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


class Ritmo:
    def __init__(self, por_seg):
        self.i, self.lock, self.prox = 1.0 / por_seg, threading.Lock(), 0.0

    def esperar(self):
        with self.lock:
            a = time.time(); t = max(a, self.prox); self.prox = t + self.i
        if t > a:
            time.sleep(t - a)


RITMO = Ritmo(20)


def num(x):
    if x is None or x == "":
        return 0.0
    return float(str(x).replace(".", "").replace(",", ".")) if isinstance(x, str) and "," in x else float(x)


def baixar_json(url):
    for tent in range(4):
        RITMO.esperar()
        try:
            req = urllib.request.Request(url, headers=H)
            with urllib.request.urlopen(req, timeout=25, context=CTX_TSE[0]) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except ssl.SSLError:
            CTX_TSE[0] = ssl._create_unverified_context()   # só para ler dados públicos do TSE
        except Exception:
            pass
        time.sleep(1 + tent)
    return None


def parse(j):
    e, v = j.get("e", {}), j.get("v", {})
    votos = {}
    for cg in j.get("carg", [])[:1]:
        for ag in cg.get("agr", []):
            for pa in ag.get("par", []):
                for c in pa.get("cand", []):
                    if not str(c.get("dvt", "Válido")).lower().startswith("anulad"):
                        votos[str(c.get("n"))] = int(num(c.get("vap")))
    return [int(num(e.get("te"))), int(num(e.get("c"))), int(num(v.get("vb"))),
            int(num(v.get("tvn", v.get("vn")))), round(num(j.get("s", {}).get("pstn", 0)), 3), votos]


def turno(cd_ele, uf):
    e6 = str(cd_ele).zfill(6)
    ab = baixar_json(f"{RAIZ}/{cd_ele}/dados/{uf}/{uf}-e{e6}-ab.json")
    if not ab:
        log(f"  {uf.upper()} ({cd_ele}): lista de municípios indisponível"); return {}, {}
    lista, nomes = [], {}
    for a in ab.get("abr", []):
        if str(a.get("tpabr", "")).lower().startswith("mu"):
            cd = str(a.get("cdabr")).zfill(5); lista.append(cd)

    def um(cd):
        j = baixar_json(f"{RAIZ}/{cd_ele}/dados/{uf}/{uf}{cd}-c0001-e{e6}-u.json")
        return cd, (parse(j) if j else None)

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for cd, p in ex.map(um, lista):
            if p:
                out[cd] = p
    if len(out) < len(lista):
        log(f"  {uf.upper()} ({cd_ele}): {len(lista) - len(out)} municípios sem arquivo")
    return out, nomes


def publicar(pid, conteudo):
    corpo = json.dumps({"token": SUPA_TOKEN, "painel_id": pid, "conteudo": conteudo},
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(f"{SUPA_URL}/rest/v1/rpc/publicar", data=corpo, method="POST",
                                 headers={"apikey": SUPA_KEY, "Content-Type": "application/json", "User-Agent": H["User-Agent"]})
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        r.read()
    return len(corpo)


def main():
    def ler(n):
        try:
            with open(os.path.join(DADOS, n), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    b22 = ler("base_mun_2022_t1t2.json")
    nomes = ler("nomes_mun.json")
    log(f"Base de 2022 no cache: {sum(len(v) for v in b22.values())} municípios")
    tudo, t0 = {}, time.time()
    for i, uf in enumerate(UFS, 1):
        t1, nm = turno(6257, uf)
        t2, nm2 = turno(6258, uf)
        nm = {cd: (nomes.get(uf) or {}).get(cd, "") for cd in set(t1) | set(t2)}
        pac = {"t1": t1, "t2": t2, "nm": nm, "x22": b22.get(uf, {})}
        tudo[uf] = pac
        try:
            tam = publicar("an:" + uf, pac)
            log(f"{i:2d}/28 {uf.upper()}: {len(t1)} munic. 1ºT, {len(t2)} munic. 2ºT — publicado ({tam/1000:.0f} KB)")
        except Exception as ex:
            log(f"{i:2d}/28 {uf.upper()}: coletado, mas a publicação falhou ({ex})")
    arq = os.path.join(DADOS, "analise_2t_2026.json")
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(tudo, f, ensure_ascii=False)
    log(f"PRONTO em {(time.time()-t0)/60:.1f} min. Cópia local: {arq}")
    log("Pode avisar o Claude: 'análise publicada'.")


if __name__ == "__main__":
    main()
