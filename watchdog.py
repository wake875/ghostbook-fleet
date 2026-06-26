#!/usr/bin/env python3
"""看门狗：检测自循环攻击是否停止，如果停了就拉起来"""
import urllib.request, json, os, time, datetime

REPO = "wake875/ghostbook-fleet"
WORKFLOW_FILE = "sustain_fleet.yml"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GH_PAT")
MAX_IDLE_MINUTES = 35  # 超过这个时间没活动就拉起

def get_workflow_id():
    url = f"https://api.github.com/repos/{REPO}/actions/workflows"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    wfs = json.loads(urllib.request.urlopen(req).read())["workflows"]
    for wf in wfs:
        if "sustain" in wf["path"]:
            return wf["id"]
    return None

def get_latest_run():
    url = f"https://api.github.com/repos/{REPO}/actions/runs?per_page=5&branch=main"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    runs = json.loads(urllib.request.urlopen(req).read())["workflow_runs"]
    for r in runs:
        if "sustain" in r.get("path", "").lower() or "sustain" in r.get("name", "").lower():
            return r
    return None

def trigger(wf_id):
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{wf_id}/dispatches"
    body = json.dumps({"ref": "main"}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req)
    return resp.status

now = datetime.datetime.now(datetime.timezone.utc)
print(f"Watchdog check: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")

run = get_latest_run()
if not run:
    print("No sustain run found! Triggering...")
    wf_id = get_workflow_id()
    if wf_id:
        status = trigger(wf_id)
        print(f"Triggered: HTTP {status}")
    else:
        print("ERROR: workflow not found!")
else:
    run_time = datetime.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    run_status = run.get("status", "?")
    run_conclusion = run.get("conclusion", "?")
    delta = (now - run_time).total_seconds() / 60
    
    print(f"Latest: {run['name'][:40]} | status={run_status} conclusion={run_conclusion}")
    print(f"Age: {delta:.0f} min ago | URL: {run['html_url']}")
    
    if run_status == "in_progress":
        print("STATUS: ACTIVE - no action needed")
    elif run_status == "queued":
        print("STATUS: QUEUED - no action needed")
    elif delta < MAX_IDLE_MINUTES:
        print(f"STATUS: OK - last run {delta:.0f} min ago (within {MAX_IDLE_MINUTES}min)")
    else:
        print(f"STATUS: STALE! {delta:.0f} min idle > {MAX_IDLE_MINUTES}min threshold")
        print("WATCHDOG: RE-TRIGGERING...")
        wf_id = get_workflow_id()
        if wf_id:
            status = trigger(wf_id)
            print(f"Triggered: HTTP {status}")
            print("WATCHDOG: CHAIN RESTARTED!")
        else:
            print("ERROR: cannot find workflow")
