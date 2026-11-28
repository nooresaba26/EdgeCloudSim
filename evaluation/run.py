"""Run each policy and seed in an isolated JVM. Requires JDK 21 and Python 3.9+."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
MAIN = "edu.boun.edgecloudsim.applications.tutorial3.RacoScenario"
BASE = dict(devices=12, feedback=3, fault="SEVERE", kappa=0.025, bMax=5, staticCap=3)
POLICIES = ["RANDOM", "SHORTEST", "REP_ONLY", "ADMISSION_ONLY", "STATIC", "FULL"]
FOCUS = ["FULL", "REP_ONLY", "STATIC"]
SEEDS = list(range(1001, 1031))
JAVA = ["java", "-XX:ActiveProcessorCount=1", "-XX:TieredStopAtLevel=1", "-Xms16m", "-Xmx160m"]

def cell(policy, **updates):
    return dict(BASE, policy=policy) | updates

def key(c):
    return "{policy}_n{devices}_d{feedback}_{fault}_k{kappa}_b{bMax}_s{staticCap}".format(**c).replace(".", "p")

def design():
    return {
        "A": [cell(p,devices=n) for n in (6,12,24,36) for p in POLICIES],
        "B": [cell(p,feedback=d) for d in (0,1,3,6) for p in FOCUS],
        "C": [cell(p,fault=f) for f in ("NORMAL","MILD","SEVERE") for p in FOCUS],
        "D": [cell("FULL"),cell("REP_ONLY"),cell("STATIC"),
              *[cell("FULL",kappa=k) for k in (0,0.01,0.05)],
              *[cell("FULL",bMax=b) for b in (3,7)],
              *[cell("STATIC",staticCap=s) for s in (2,4)]],
    }

def csv_write(path, rows):
    rows = list(rows)
    if not rows: return
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix(".writing")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)

def digest(p):
    raw=p.read_bytes()
    if p.suffix!=".jar": raw=raw.replace(b"\r\n",b"\n")
    return hashlib.sha256(raw).hexdigest()

def compile_java(repo, build, jars, original=False):
    build.mkdir(parents=True,exist_ok=True)
    sources=([repo/"src"/(MAIN.replace(".","/")+".java")] if original else sorted((HERE/"overlay").glob("*.java")))
    subprocess.run([*JAVA,"-m","jdk.compiler/com.sun.tools.javac.Main","-encoding","UTF-8","-cp",
                    os.pathsep.join(map(str,jars)),"-sourcepath",str(repo/"src"),"-d",str(build),*map(str,sources)],
                   cwd=repo,check=True)

def line_from(rows):
    states=[r["terminal"] for r in rows]
    assigned=sum(r["host"]!="" for r in rows)
    a=states.count("OK")
    return (f"Offered={len(rows)} Assigned={assigned} Accepted={a} Failed={assigned-a} "
            f"NoFeasible={states.count('NO_FEASIBLE')} CapFull={states.count('CAP_FULL')} Pending=0")

def run_one(repo,root,cp,c,seed):
    folder=root/"raw"/key(c)
    folder.mkdir(exist_ok=True,parents=True)
    dest=folder/f"seed-{seed}.csv.gz"
    if dest.exists(): return 0
    with tempfile.TemporaryDirectory(dir=folder) as td:
        tmp=Path(td)
        trace=tmp/"tasks.csv"
        args=["-Dedgecloudsim.seed="+str(seed),"-Draco.tasks="+str(trace)]
        args.extend(f"-Draco.{k}={v}" for k,v in c.items())
        p=subprocess.run([*JAVA,*args,"-cp",cp,MAIN],cwd=repo,capture_output=True,text=True)
        if p.returncode or not trace.is_file():
            raise RuntimeError(f"{key(c)} / {seed}\n{p.stderr[-2000:]}\n{p.stdout[-1500:]}")
        with trace.open(newline="") as f: rows=list(csv.DictReader(f))
        if line_from(rows) not in p.stdout.splitlines():
            raise RuntimeError(f"Java summary differs from trace at {key(c)} / {seed}")
        with (tmp/"tasks.gz").open("wb") as out, gzip.GzipFile(filename="",fileobj=out,mode="wb",mtime=0,compresslevel=5) as z:
            with trace.open("rb") as src: shutil.copyfileobj(src,z)
        (tmp/"tasks.gz").replace(dest)
    return 1

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=["plan","pilot","A","B","C","D","all"])
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--jobs",type=int,default=2)
    a=p.parse_args()
    if a.jobs<1: p.error("--jobs must be positive")
    repo=a.repo.resolve()
    out=a.out.resolve()
    out.mkdir(exist_ok=True,parents=True)
    design_rows={}
    stages=design()
    for label,items in stages.items():
        for c in items:
            rec=design_rows.setdefault(key(c),dict(setting=key(c),experiments="",**c))
            rec["experiments"]+=label
    csv_write(out/"design.csv",design_rows.values())
    if a.stage=="plan":
        print(f"{len(design_rows)} settings x {len(SEEDS)} seeds = {len(design_rows)*len(SEEDS)} unique production runs.")
        return
    inputs=json.loads((HERE/"source_sha256.json").read_text())
    for name,sha in inputs.items():
        if not (repo/name).is_file() or digest(repo/name)!=sha:
            raise ValueError("Source differs at "+name+". Use the uploaded archive revision.")
    jv=subprocess.run(["java","-version"],capture_output=True,text=True,check=True)
    signature={"archive_commit":"c1281ee87799e260d559cbad17cb4ff636ca9c06","java":(jv.stdout+jv.stderr).strip(),
               "files":{p.relative_to(HERE).as_posix():digest(p) for p in [HERE/"run.py",HERE/"source_sha256.json",*sorted((HERE/"overlay").glob("*.java"))]},
               "seeds":SEEDS}
    stamp=out/"run_version.json"
    if stamp.exists() and json.loads(stamp.read_text())!=signature:
        raise ValueError("Code or Java differs from the previous run. Use another --out directory.")
    if not stamp.exists(): stamp.write_text(json.dumps(signature,indent=2)+"\n")
    (out/"host.json").write_text(json.dumps({"system":platform.platform(),"python":sys.version},indent=2)+"\n")
    jars=sorted((repo/"lib").glob("*.jar"))
    build=out/".build"
    compile_java(repo,build,jars)
    cp=os.pathsep.join(map(str,[build,*jars]))
    if a.stage=="pilot":
        legacy=out/".original"
        compile_java(repo,legacy,jars,original=True)
        command=[*JAVA,"-Dedgecloudsim.seed=42","-cp",os.pathsep.join(map(str,[legacy,*jars])),MAIN]
        original=subprocess.run(command,cwd=repo,check=True,capture_output=True,text=True)
        line=next(x for x in original.stdout.splitlines() if x.startswith("Offered="))
        (out/"pilot_original.txt").write_text(line+"\n")
        cases=[(cell(p),42) for p in ("FULL","REP_ONLY")]
        root=out/"pilot"
    else:
        selected=(stages.values() if a.stage=="all" else [stages[a.stage]])
        unique={key(c):c for group in selected for c in group}
        cases=[(c,seed) for c in unique.values() for seed in SEEDS]
        root=out
    count=0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        jobs=[pool.submit(run_one,repo,root,cp,c,seed) for c,seed in cases]
        for i,j in enumerate(as_completed(jobs),1):
            count+=j.result()
            if i%100==0: print(f"{i}/{len(cases)} complete",flush=True)
    if a.stage=="pilot":
        pilot=[]
        for c,seed in cases:
            with gzip.open(root/"raw"/key(c)/f"seed-{seed}.csv.gz","rt",newline="") as f:
                report=line_from(list(csv.DictReader(f)))
            print(c["policy"],report)
            if c["policy"]=="FULL" and report!=line: raise ValueError("Pilot differs from original.")
            pilot.append(dict(policy=c["policy"],seed=seed,summary=report))
        csv_write(out/"pilot.csv",pilot)
    print(f"{count} newly completed, {len(cases)-count} reused.")
if __name__=="__main__":
    main()
