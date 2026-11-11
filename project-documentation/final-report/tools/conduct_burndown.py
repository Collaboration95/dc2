#!/usr/bin/env python3
"""Rebuild the report's project-conduct charts from GitHub issue timestamps.

Refresh and render (all GitHub reads use gh):
  python tools/conduct_burndown.py --refresh
Render the retained snapshot without network access:
  python tools/conduct_burndown.py
Dependencies: matplotlib (version recorded in data/conduct-chart-summary.json).
Use a disposable environment, e.g. /private/tmp/conduct-report-venv.

Outputs (figures/):
  conduct-iteration-plan.png      planned iteration timeline with WBS packages and milestones
  conduct-overall-issues.png      overall burnup: issues registered against issues closed
  conduct-iteration-burndown.png  per iteration: registered, closed and open at iteration end
  conduct-issue-reduction.png     open tasks and parent epics over time

Counts use createdAt and the latest closedAt. Issues labelled epic are counted as
parent epics. All days use Asia/Singapore; the snapshot day stops at the capture time.
Charts are drawn at their printed width (15 cm) so that 8 pt text prints at 8 pt.
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
# Iteration windows: (number, name, start, end, WBS packages, leads).
PERIODS = [
    (1, 'Baseline and domain', date(2026, 10, 5), date(2026, 10, 9), 'WBS 1–2', 'Guruprasath, Long'),
    (2, 'Local services', date(2026, 10, 10), date(2026, 10, 14), 'WBS 3, 4, 6', 'Ibrahim, Long'),
    (3, 'AWS delivery', date(2026, 10, 15), date(2026, 10, 20), 'WBS 5, 7, 8', 'Guruprasath, Ibrahim, Long'),
    (4, 'Hardening and presentation', date(2026, 10, 21), date(2026, 10, 26), 'WBS 9–10', 'All'),
    (5, 'Feedback and report', date(2026, 10, 27), date(2026, 11, 16), 'WBS 10', 'All'),
]
MILESTONES = [  # (date, label, label row, alignment)
    (date(2026, 10, 4), 'Proposal', 0, 'left'),
    (date(2026, 10, 18), 'project2-v1', 1, 'right'),
    (date(2026, 10, 20), 'Freeze', 1, 'left'),
    (date(2026, 10, 26), 'Presentation', 0, 'left'),
    (date(2026, 11, 16), 'Report due', 1, 'right'),
]
BLUE, GREEN, ORANGE, GREY = '#235b85', '#22856b', '#b96c28', '#5b6472'
BAND = '#eef1f5'
WIDTH_IN = 15 / 2.54  # printed width in the report


def instant(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(SGT) if s else None


def midnight(d):
    return datetime.combine(d, time.min, SGT)


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


def style():
    plt.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 8.5, 'axes.titlesize': 9.5,
        'axes.titleweight': 'bold', 'axes.labelsize': 8.5, 'xtick.labelsize': 8,
        'ytick.labelsize': 8, 'legend.fontsize': 8, 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.linewidth': 0.6, 'lines.linewidth': 1.6,
        'savefig.facecolor': 'white', 'figure.facecolor': 'white'})


def save(fig, name):
    fig.savefig(ROOT / 'figures' / name, dpi=300)
    plt.close(fig)


def iteration_bands(ax, top_label=True):
    """Shade alternate iteration windows lightly and number them at the top."""
    for i, (n, _, a, b, _, _) in enumerate(PERIODS):
        left, right = midnight(a), midnight(b + timedelta(days=1))
        if i % 2 == 0:
            ax.axvspan(left, right, color=BAND, zorder=0, lw=0)
        if top_label:
            ax.text(left + (right - left) / 2, 1.0, f'It. {n}',
                    transform=ax.get_xaxis_transform(), ha='center', va='bottom',
                    fontsize=8, color=GREY)


def date_axis(ax):
    ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=[1, 8, 15, 22], tz=SGT))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b', tz=SGT))
    ax.set_xlim(midnight(PERIODS[0][2] - timedelta(days=1)),
                midnight(PERIODS[-1][3] + timedelta(days=1)))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis='y', alpha=.25, lw=.5)
    ax.set_ylim(bottom=0)


def snapshot_line(ax, captured, label=True):
    ax.axvline(captured, color=GREY, lw=.8, ls=':')
    if label:
        ax.text(captured, .97, ' Snapshot\n 10 Nov', transform=ax.get_xaxis_transform(),
                ha='left', va='top', fontsize=8, color=GREY)


def span(a, b):
    if a.month == b.month:
        return f'{a.day}–{b.day} {b:%b}'
    return f'{a.day} {a:%b}–{b.day} {b:%b}'


def plan_chart():
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.8))
    for i, (n, name, a, b, wbs, leads) in enumerate(PERIODS):
        y = len(PERIODS) - i
        left, right = midnight(a), midnight(b + timedelta(days=1))
        ax.barh(y, right - left, left=left, height=.62, color=BLUE, alpha=.85, zorder=2)
        label = f'{wbs} · {leads}'
        if n == 5:
            ax.text(left + timedelta(hours=10), y, label, va='center', ha='left',
                    fontsize=8, color='white', zorder=3)
        else:
            ax.text(right + timedelta(hours=8), y, label, va='center', ha='left', fontsize=8,
                    color='#1f2937', zorder=3,
                    bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': 1})
    ax.set_yticks([len(PERIODS) - i for i in range(len(PERIODS))])
    ax.set_yticklabels([f'{n}  {name}\n{span(a, b)}' for n, name, a, b, _, _ in PERIODS])
    top = len(PERIODS) + .75
    for d, name, row, ha in MILESTONES:
        x = midnight(d) + timedelta(hours=12)
        ax.axvline(x, color=ORANGE, lw=.6, ls='--', zorder=1, ymax=.93)
        ax.plot([x], [top], marker='D', color=ORANGE, ms=4, zorder=3, clip_on=False)
        shift = timedelta(hours=14) * (1 if ha == 'left' else -1)
        ax.text(x + shift, top + row * .55, f'{name} {d.day} {d:%b}', fontsize=8, va='center',
                ha=ha, color=ORANGE, clip_on=False, zorder=4,
                bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': .5})
    ax.set_ylim(.4, top + .75)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)
    ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=[1, 8, 15, 22], tz=SGT))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b', tz=SGT))
    ax.set_xlim(midnight(date(2026, 10, 3)), midnight(date(2026, 11, 17)))
    ax.grid(axis='x', alpha=.25, lw=.5)
    fig.tight_layout(pad=.4)
    save(fig, 'conduct-iteration-plan.png')


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
    start, end = PERIODS[0][2], min(PERIODS[-1][3], captured.date())
    days = [start - timedelta(days=1) + timedelta(days=i) for i in range((end - start).days + 2)]
    # Day 0 is the opening balance before the first reporting day; the last day ends at capture.
    limits = [min(midnight(d + timedelta(days=1)), captured + timedelta(microseconds=1)) for d in days]

    def counts(group):
        opened = [sum(x['created'] < t for x in group) for t in limits]
        closed = [sum(bool(x['closed'] and x['closed'] < t) for x in group) for t in limits]
        return opened, closed, [a - b for a, b in zip(opened, closed)]

    tasks = [x for x in issues if not x['epic']]
    epics = [x for x in issues if x['epic']]
    tasks_opened, tasks_closed, tasks_left = counts(tasks)
    epics_opened, epics_closed, epics_left = counts(epics)
    total_opened, total_closed, total_left = counts(issues)
    assert total_left[-1] == sum(not x['closed'] for x in issues)
    with (ROOT / 'data/conduct-daily-issues.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date_sgt', 'tasks_created', 'tasks_closed', 'tasks_remaining',
                    'epics_created', 'epics_closed', 'epics_remaining', 'all_remaining'])
        w.writerows(zip(days, tasks_opened, tasks_closed, tasks_left,
                        epics_opened, epics_closed, epics_left, total_left))

    style()
    plan_chart()
    # Plot each daily balance at the end of its day so that steps line up with dates.
    xs = [midnight(d + timedelta(days=1)) for d in days[:-1]] + [captured]
    xs[0] = midnight(days[1])

    # Overall burnup: scope registered against issues closed.
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.9))
    iteration_bands(ax)
    ax.step(xs, total_opened, where='pre', color=BLUE, label='Issues registered (scope)')
    ax.step(xs, total_closed, where='pre', color=GREEN, label='Issues closed')
    ax.fill_between(xs, total_closed, total_opened, step='pre', color=ORANGE, alpha=.18,
                    lw=0, label='Open (gap)')
    ax.text(captured, total_opened[-1] + 4, f'{total_opened[-1]} registered  ', ha='right',
            va='bottom', fontsize=8, color=BLUE)
    ax.text(captured, total_closed[-1] - 6, f'{total_closed[-1]} closed  ', ha='right',
            va='top', fontsize=8, color=GREEN)
    snapshot_line(ax, captured, label=False)
    ax.text(captured, .03, 'Snapshot  ', transform=ax.get_xaxis_transform(), ha='right',
            va='bottom', fontsize=8, color=GREY)
    date_axis(ax)
    ax.set_ylim(0, total_opened[-1] * 1.18)
    ax.set_ylabel('Cumulative issues')
    ax.legend(loc='lower right', frameon=False, bbox_to_anchor=(.86, .14))
    fig.tight_layout(pad=.4)
    save(fig, 'conduct-overall-issues.png')

    # Per-iteration summary: registered, closed, open at iteration end.
    period_summary = []
    for n, name, a, b, _, _ in PERIODS:
        lo = midnight(a)
        hi = min(midnight(b + timedelta(days=1)), captured + timedelta(microseconds=1))
        opening = sum(x['created'] < lo and not (x['closed'] and x['closed'] < lo) for x in issues)
        added = sum(lo <= x['created'] < hi for x in issues)
        closed = sum(bool(x['closed'] and lo <= x['closed'] < hi) for x in issues)
        ending = sum(x['created'] < hi and not (x['closed'] and x['closed'] < hi) for x in issues)
        assert ending == opening + added - closed
        period_summary.append({
            'iteration': f'{n} · {name}', 'start': str(a), 'planned_end': str(b),
            'observed_through': str(min(b, end)), 'opening_open': opening, 'new_issues': added,
            'closures': closed, 'ending_open': ending,
            'ending_tasks': sum(not x['epic'] and x['created'] < hi and not (x['closed'] and x['closed'] < hi) for x in issues),
            'ending_epics': sum(x['epic'] and x['created'] < hi and not (x['closed'] and x['closed'] < hi) for x in issues)})
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.9))
    width = .26
    series = [('Registered', 'new_issues', BLUE), ('Closed', 'closures', GREEN),
              ('Open at iteration end', 'ending_open', ORANGE)]
    for k, (label, key, color) in enumerate(series):
        xs_bar = [i + (k - 1) * width for i in range(len(PERIODS))]
        vals = [p[key] for p in period_summary]
        ax.bar(xs_bar, vals, width=width * .92, color=color, label=label, zorder=2)
        for x, v in zip(xs_bar, vals):
            ax.text(x, v + 2, str(v), ha='center', va='bottom', fontsize=8, color='#1f2937')
    ax.set_xticks(range(len(PERIODS)))
    short = {1: 'Baseline', 2: 'Local services', 3: 'AWS delivery', 4: 'Hardening', 5: 'Report'}
    ax.set_xticklabels([f'{n} · {short[n]}\n{span(a, min(b, end))}' for n, _, a, b, _, _ in PERIODS])
    ax.set_ylabel('Issues')
    ax.set_ylim(0, 140)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 5, 10]))
    ax.grid(axis='y', alpha=.25, lw=.5, zorder=0)
    ax.tick_params(axis='x', length=0)
    ax.legend(frameon=False, loc='upper right')
    fig.tight_layout(pad=.4)
    save(fig, 'conduct-iteration-burndown.png')

    # Issue reduction: open tasks and open parent epics, stacked.
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 2.6))
    iteration_bands(ax)
    ax.stackplot(xs, tasks_left, epics_left, step='pre', colors=[BLUE, ORANGE], alpha=.75,
                 labels=['Open tasks', 'Open parent epics'], lw=0)
    ax.step(xs, total_left, where='pre', color='#1f2937', lw=.9)
    peak = max(total_left)
    idx = total_left.index(peak)
    ax.annotate(f'Peak {peak} open', xy=(xs[idx], peak), xytext=(8, 2), textcoords='offset points',
                fontsize=8, va='bottom')
    ax.annotate(f'{total_left[-1]} open ({tasks_left[-1]} tasks, {epics_left[-1]} epic)',
                xy=(captured, total_left[-1]), xytext=(-6, 10), textcoords='offset points',
                fontsize=8, ha='right', va='bottom')
    date_axis(ax)
    ax.set_ylim(0, peak * 1.25)
    ax.set_ylabel('Open issues')
    ax.legend(frameon=False, loc='upper right', bbox_to_anchor=(1.0, .9))
    fig.tight_layout(pad=.4)
    save(fig, 'conduct-issue-reduction.png')

    summary = {'snapshot_at': captured.isoformat(), 'timezone': 'Asia/Singapore',
               'matplotlib': matplotlib.__version__,
               'input_sha256': hashlib.sha256((ROOT / 'data/conduct-issues.csv').read_bytes()).hexdigest(),
               'registered': total_opened[-1], 'closed': total_closed[-1], 'open': total_left[-1],
               'tasks': len(tasks), 'epics': len(epics), 'iterations': period_summary,
               'semantics': 'createdAt and latest closedAt; issues labelled epic counted as parent epics.'}
    (ROOT / 'data/conduct-chart-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
