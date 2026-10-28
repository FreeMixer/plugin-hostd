import os, sys, re, time, json, subprocess
sys.argv = ["x"]
src = open("/root/omx-run/gvp.py").read()
head = src.split("def run(")[0]
exec(head)
PT = "https://www.modartt.com/lv2/Pianoteq9"
env["LV2_PATH"] += ":/zynthian/zynthian-sw/pianoteq/arm-64bit"
def runpt(rate, stress):
    srv = f"pt{rate}"; env["JACK_DEFAULT_SERVER"] = srv
    jack = subprocess.Popen(["jackd","-n",srv,"-d","dummy","-r",str(rate),"-p","256"],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
    time.sleep(3)
    os.makedirs("/run/plugin-hostd-gvp", exist_ok=True)
    hd = subprocess.Popen(["plugin-hostd","-n","-p",str(PORT),"-c","/root/omx-run/gvp.conf"],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
    extra = []
    try:
        for _ in range(50):
            try: h = Hostd(); break
            except OSError: time.sleep(0.2)
        t0 = time.monotonic(); r = h.call(f"add {PT} 0"); add_ms = (time.monotonic()-t0)*1000
        if not r.startswith("resp") or int(r.split()[1]) < 0: raise RuntimeError(r)
        wl = h.call("worker_list"); pids = [hd.pid] + [int(w.split(":")[1]) for w in wl.split()[2:]]
        time.sleep(3)
        ports = subprocess.run(["jack_lsp"],env=env,capture_output=True,text=True).stdout.split()
        midi = [p for p in ports if p.startswith("effect_0:midi")]; outs = [p for p in ports if p.startswith("effect_0:out_")]
        seq = subprocess.Popen(["jack_midiseq","seq","80000","0","60","70000","0","64","70000","0","67","70000","0","72","70000","0","76","70000"],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
        extra.append(seq); time.sleep(1)
        subprocess.run(["jack_connect","seq:out","effect_0:midi_in"],env=env)
        if stress:
            for _ in range(8): extra.append(subprocess.Popen([sys.executable,"-c","while True: pass"]))
            time.sleep(2)
        peak = subprocess.Popen(["/root/omx-run/jackpeak","effect_0:out_1",str(WINDOW+2)],env=env,stdout=subprocess.PIPE,text=True)
        time.sleep(1); a = pids_stats(pids); ta = time.monotonic(); time.sleep(WINDOW); b = pids_stats(pids); tb = time.monotonic()
        out = peak.communicate()[0]; m = re.search(r"cpu_avg ([\d.]+) cpu_max ([\d.]+) xruns (\d+) peak ([\d.]+) rms ([\d.]+)", out)
        return dict(rate=rate, stress=stress, midi_ports=midi, outs=len(outs), processes=len(pids), rss_mb=round(b[0]/1024,1), pss_mb=round(b[1]/1024,1),
                    cpu_pct=round((b[2]-a[2])/TCK/(tb-ta)*100,2), dsp_load_avg=float(m[1]), dsp_load_max=float(m[2]), xruns=int(m[3]), peak=float(m[4]), rms=float(m[5]), add_ms=round(add_ms))
    finally:
        for p in extra: p.kill()
        try: h.call("quit")
        except Exception: pass
        hd.terminate(); jack.terminate()
        try: hd.wait(5); jack.wait(5)
        except Exception: hd.kill(); jack.kill()
        subprocess.run(["pkill","-x","omx-clap-host"],stderr=subprocess.DEVNULL); subprocess.run(["pkill","-x","jack_midiseq"],stderr=subprocess.DEVNULL); time.sleep(2)
for rate in (48000, 96000):
    for stress in (False, True):
        try: r = runpt(rate, stress)
        except Exception as e: r = dict(rate=rate, stress=stress, error=repr(e))
        print(json.dumps(r), flush=True)
