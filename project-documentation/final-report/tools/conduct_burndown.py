#!/usr/bin/env python3
"""Rebuild report issue charts from authenticated gh issue timestamps.

Refresh and render (all GitHub reads use gh):
  python conduct_burndown.py --refresh
Render the retained snapshot without network access:
  python conduct_burndown.py
Dependencies: matplotlib (tested with version recorded in conduct-chart-summary.json).
Use a disposable environment, e.g. /private/tmp/conduct-report-venv.

Counts describe issue administration, not effort or accepted story points. Parent
issues labelled epic are separate. Latest closedAt cannot recover reopen cycles.
All days use Asia/Singapore; the snapshot day stops at the actual capture time.
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from zoneinfo import ZoneInfo

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'conduct-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parents[1]
SGT = ZoneInfo('Asia/Singapore')
REPO = 'Collaboration95/dc2'
PERIODS = [
    ('1 · Baseline / domain', date(2026, 10, 5), date(2026, 10, 9)),
    ('2 · Local services', date(2026, 10, 10), date(2026, 10, 14)),
    ('3 · AWS delivery', date(2026, 10, 15), date(2026, 10, 20)),
    ('4 · Hardening / presentation', date(2026, 10, 21), date(2026, 10, 26)),
    ('5 · Feedback / report', date(2026, 10, 27), date(2026, 11, 16)),
]
BLUE, GREEN, ORANGE = '#235b85', '#22856b', '#b96c28'


def instant(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(SGT) if s else None


def refresh():
    args = ['gh', 'issue', 'list', '--repo', REPO, '--state', 'all', '--limit', '500',
            '--json', 'number,createdAt,closedAt,labels,title']
    rows = json.loads(subprocess.check_output(args, text=True))
    if len(rows) >= 500:
        raise SystemExit('Issue limit reached: raise the limit before publishing charts.')
    with (ROOT / 'data/conduct-issues.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['number', 'createdAt', 'closedAt', 'labels', 'title'])
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r['number']):
            writer.writerow({**row, 'closedAt': row['closedAt'] or '',
                             'labels': json.dumps([x['name'] for x in row['labels']], ensure_ascii=False)})
    (ROOT / 'data/conduct-issue-capture.json').write_text(json.dumps({
        'snapshot_at': datetime.now(timezone.utc).isoformat(), 'command': args,
        'repo': REPO, 'issues': len(rows)}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    opts = parser.parse_args()
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'figures').mkdir(exist_ok=True)
    if opts.refresh:
        refresh()
    meta = ROOT / 'data/conduct-issue-capture.json'
    if not meta.exists():
        meta = ROOT / 'data/conduct-snapshot.json'
    captured = instant(json.loads(meta.read_text())['snapshot_at'])
    rows = list(csv.DictReader((ROOT / 'data/conduct-issues.csv').open()))
    assert len({r['number'] for r in rows}) == len(rows), 'Duplicate issue IDs'
    issues = [{'number': int(r['number']), 'created': instant(r['createdAt']),
               'closed': instant(r['closedAt']), 'epic': 'epic' in json.loads(r['labels'])}
              for r in rows]
    assert all(x['created'] <= captured for x in issues), 'Issue created after snapshot'
    assert all(not x['closed'] or x['created'] <= x['closed'] <= captured for x in issues)
    start, end = PERIODS[0][1], min(PERIODS[-1][2], captured.date())
    days = [start - timedelta(days=1) + timedelta(days=i)
            for i in range((end - start).days + 2)]
    # Day 0 is the opening balance before the first reporting day.
    limits = [min(datetime.combine(d + timedelta(days=1), time.min, SGT), captured) for d in days]
    def counts(epic):
        group = [x for x in issues if x['epic'] == epic]
        opened = [sum(x['created'] < t for x in group) for t in limits]
        closed = [sum(bool(x['closed'] and x['closed'] < t) for x in group) for t in limits]
        return opened, closed, [a-b for a,b in zip(opened,closed)]
    tasks_opened, tasks_closed, tasks_left = counts(False)
    epics_opened, epics_closed, epics_left = counts(True)
    total_opened = [a+b for a,b in zip(tasks_opened, epics_opened)]
    total_closed = [a+b for a,b in zip(tasks_closed, epics_closed)]
    total_left = [a-b for a,b in zip(total_opened, total_closed)]
    # Include events exactly at capture time in the final observation.
    for group, opened, closed, left in [
        ([x for x in issues if not x['epic']], tasks_opened, tasks_closed, tasks_left),
        ([x for x in issues if x['epic']], epics_opened, epics_closed, epics_left)]:
        opened[-1] = len(group)
        closed[-1] = sum(bool(x['closed']) for x in group)
        left[-1] = opened[-1] - closed[-1]
    total_opened[-1], total_closed[-1] = len(issues), sum(bool(x['closed']) for x in issues)
    total_left[-1] = total_opened[-1] - total_closed[-1]
    assert total_left[-1] == sum(not x['closed'] for x in issues)
    with (ROOT / 'data/conduct-daily-issues.csv').open('w', newline='') as f:
        w=csv.writer(f); w.writerow(['date_sgt','tasks_created','tasks_closed','tasks_remaining',
                                    'epics_created','epics_closed','epics_remaining','all_remaining'])
        w.writerows(zip(days,tasks_opened,tasks_closed,tasks_left,epics_opened,epics_closed,epics_left,total_left))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':14,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.titleweight':'bold','savefig.facecolor':'white'})
    stamp = captured.strftime('%d %b %Y, %H:%M SGT')
    def format_axis(ax):
        ax.yaxis.set_major_locator(MaxNLocator(integer=True));ax.grid(axis='y',alpha=.2)
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b', tz=SGT))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4,maxticks=8))
    def save(fig, name, bottom=.12):
        fig.text(.07,.025,f'GitHub createdAt / latest closedAt · {stamp}\nIssue counts; closures include administrative dispositions. No story points or ideal sprint line.',
                 fontsize=11,color='#4b5563')
        fig.tight_layout(rect=(0,bottom,1,.98))
        fig.savefig(ROOT/'figures'/name,dpi=190)
        plt.close(fig)
    fig, axes=plt.subplots(2,1,figsize=(10,7.1),sharex=True)
    ax=axes[0]
    ax.step(days,tasks_opened,where='post',label=f'Tasks registered ({tasks_opened[-1]})',color=BLUE)
    ax.step(days,tasks_closed,where='post',label=f'Tasks closed ({tasks_closed[-1]})',color=GREEN)
    ax.step(days,epics_opened,where='post',label=f'Parent epics registered ({epics_opened[-1]})',color=ORANGE,linestyle='--')
    ax.step(days,epics_closed,where='post',label=f'Parent epics closed ({epics_closed[-1]})',color='#80627d',linestyle=':')
    ax.set_title(f'Overall issue burnup · {start.strftime("%d %B")}–{end.strftime("%d %B %Y")}',loc='left');ax.set_ylabel('Cumulative issues')
    ax.legend(loc='center left',bbox_to_anchor=(.55,.43),fontsize=12,frameon=False)
    ax=axes[1]
    ax.step(days,tasks_left,where='post',label=f'Tasks remaining ({tasks_left[-1]})',color=BLUE,linewidth=2)
    ax.step(days,epics_left,where='post',label=f'Parent epics remaining ({epics_left[-1]})',color=ORANGE,linestyle='--')
    ax.set_title('Overall issue burndown · scope additions remain visible',loc='left');ax.set_ylabel('Open issues')
    ax.legend(loc='upper right',fontsize=12,frameon=False)
    for ax in axes:format_axis(ax)
    save(fig,'conduct-overall-issues.png')
    fig, axes=plt.subplots(3,2,figsize=(11,11))
    period_summary=[]
    for ax,(title,a,b) in zip(axes.flat,PERIODS):
        observed_end=min(b,end)
        ids=[i for i,d in enumerate(days) if a-timedelta(days=1)<=d<=observed_end]
        period_start = datetime.combine(a, time.min, SGT)
        period_end = min(datetime.combine(b + timedelta(days=1), time.min, SGT), captured)
        points = sorted({period_start, period_end} | {
            t for x in issues for t in [x['created'], x['closed']]
            if t and period_start <= t <= period_end})
        for epic, color, style, label in [(False,BLUE,'-','Tasks'), (True,ORANGE,'--','Parent epics')]:
            remaining = [sum(x['epic']==epic and x['created']<=t and
                             (not x['closed'] or x['closed']>t) for x in issues) for t in points]
            ax.step(points, remaining, where='post', color=color, linestyle=style, label=label)
        ax.set_title(title+'\n'+a.strftime('%d %b')+'–'+b.strftime('%d %b'),loc='left',fontsize=14)
        ax.set_xlim(period_start, datetime.combine(b + timedelta(days=1), time.min, SGT))
        if b>end:
            ax.axvspan(captured,datetime.combine(b+timedelta(days=1),time.min,SGT),color='#e8ebef',alpha=.8)
            ax.text(.69,.76,'Not yet\nobserved',transform=ax.transAxes,fontsize=11,color='#596170')
        format_axis(ax);ax.tick_params(axis='x',labelsize=11);ax.set_ylabel('Open issues')
        if not any(x['created'] < period_end for x in issues):
            ax.set_ylim(0,1);ax.text(.5,.55,'No GitHub issues registered',ha='center',transform=ax.transAxes,fontsize=11)
        i,j=ids[0],ids[-1]
        period_summary.append({'iteration':title,'start':str(a),'planned_end':str(b),'observed_through':str(observed_end),
            'opening_open':total_left[i],'new_issues':total_opened[j]-total_opened[i],
            'closures':total_closed[j]-total_closed[i],'ending_open':total_left[j],
            'ending_tasks':tasks_left[j],'ending_epics':epics_left[j]})
    axes.flat[5].axis('off')
    axes.flat[5].text(0,.9,'Iteration issue burndown',weight='bold',fontsize=15)
    axes.flat[5].text(0,.76,'Blue: tasks    Dashed: parent epics\n\nPanels use creation / latest closure times.\nOpening backlog and additions remain visible.\nIteration 5 stops at the snapshot.\nWindows summarise delivery phases.\n\nLatest timestamps cannot recover\nreopen cycles.',va='top',fontsize=12,linespacing=1.6)
    save(fig,'conduct-iteration-burndown.png',bottom=.10)
    fig,ax=plt.subplots(figsize=(10,4.5))
    ax.step(days,total_left,where='post',color=BLUE,linewidth=2,label='All open issues (tasks + parent epics)')
    ax.fill_between(days,total_left,step='post',color=BLUE,alpha=.10)
    peak=max(total_left);idx=total_left.index(peak)
    ax.annotate(f'Daily peak: {peak}',xy=(days[idx],peak),xytext=(12,8),textcoords='offset points',fontsize=10)
    ax.annotate(f'{total_left[-1]} open at snapshot',xy=(days[-1],total_left[-1]),xytext=(-160,25),
                textcoords='offset points',arrowprops={'arrowstyle':'-','color':BLUE},fontsize=10)
    ax.set_title('Issue reduction · open issues over time',loc='left');ax.set_ylabel('Open issues')
    format_axis(ax);ax.set_ylim(top=peak*1.22);ax.legend(frameon=False,loc='upper right',fontsize=12)
    save(fig,'conduct-issue-reduction.png',bottom=.20)
    summary={'snapshot_at':captured.isoformat(),'timezone':'Asia/Singapore','matplotlib':matplotlib.__version__,
        'input_sha256':hashlib.sha256((ROOT/'data/conduct-issues.csv').read_bytes()).hexdigest(),
        'registered':total_opened[-1],'closed':total_closed[-1],'open':total_left[-1],
        'tasks':tasks_opened[-1],'epics':epics_opened[-1],'iterations':period_summary,
        'semantics':'Latest createdAt/closedAt; reopening history unavailable; all closure reasons counted as administrative closure.'}
    (ROOT/'data/conduct-chart-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
