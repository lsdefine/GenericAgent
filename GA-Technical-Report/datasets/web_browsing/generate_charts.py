import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['PingFang SC', 'Arial Unicode MS', 'Heiti SC']
matplotlib.rcParams['axes.unicode_minus'] = False
import numpy as np
import os

OUT = os.path.dirname(os.path.abspath(__file__))

# ── DATA ─────────────────────────────────────────────────────
ga_bc_tokens = [124430, 479575, 46860, 380227, 264714, 656485, 975406, 117027, 1012941, 656021]
oc_bc_tokens = [508837, 2041823, 842206, 2470125, 893822, 648316, 3624829, 568746, 468366, 1066935]
ga_bc_score  = [1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0]
oc_bc_score  = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]

ga_wc_tokens = [104950, 23008, 127827, 573031, 330326, 549254, 100705, 26685, 61670, 104467, 16206, 196025]
oc_wc_tokens = [90017, 767679, 401739, 761695, 431698, 515775, 262124, 493914, 1082896, 2946267, 377221, 348109]
ga_wc_score  = [1.0, 0.667, 1.0, 0.667, 1.0, 0.667, 0.667, 1.0, 0.667, 0.667, 1.0, 1.0]
oc_wc_score  = [1.0, 0.667, 1.0, 0.667, 1.0, 0.0, 0.667, 0.75, 1.0, 0.667, 1.0, 0.25]

# ── STYLE ────────────────────────────────────────────────────
BG      = '#FAFBFC'
GA_BAR  = '#3B82F6'
OC_BAR  = '#EF4444'
GA_DOT  = '#1D4ED8'
OC_DOT  = '#B91C1C'
GRID_C  = '#E5E7EB'
TEXT_C  = '#1F2937'
SUB_C   = '#6B7280'

# ── METRICS ──────────────────────────────────────────────────
datasets = ['BrowseComp-ZH', 'WebCanvas']

ga_tok = [np.mean(ga_bc_tokens)/1000, np.mean(ga_wc_tokens)/1000]   # K
oc_tok = [np.mean(oc_bc_tokens)/1000, np.mean(oc_wc_tokens)/1000]

ga_rate = [np.mean(ga_bc_score)*100, np.mean(ga_wc_score)*100]      # %
oc_rate = [np.mean(oc_bc_score)*100, np.mean(oc_wc_score)*100]

# ── PLOT ─────────────────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(9, 5.5))
fig.patch.set_facecolor(BG)
ax1.set_facecolor(BG)

x = np.arange(len(datasets))
w = 0.28

# bars — token consumption
bars_ga = ax1.bar(x - w/2, ga_tok, w,
                  color=GA_BAR, edgecolor='white', linewidth=1.5,
                  zorder=3, alpha=0.85, label='GA — Token')
bars_oc = ax1.bar(x + w/2, oc_tok, w,
                  color=OC_BAR, edgecolor='white', linewidth=1.5,
                  zorder=3, alpha=0.85, label='OC — Token')

# bar labels
for bar in bars_ga:
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 18,
             f'{bar.get_height():.0f}K', ha='center', va='bottom',
             fontsize=10, fontweight='bold', color=GA_DOT)
for bar in bars_oc:
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 18,
             f'{bar.get_height():.0f}K', ha='center', va='bottom',
             fontsize=10, fontweight='bold', color=OC_DOT)

# style left axis
ax1.set_ylabel('平均 Token 消耗 (K)  ↓ 越低越好', fontsize=11, color=SUB_C)
ax1.set_xticks(x)
ax1.set_xticklabels(datasets, fontsize=13, fontweight='bold')
ax1.set_ylim(0, max(max(ga_tok), max(oc_tok)) * 1.45)
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)
ax1.spines['left'].set_color(GRID_C)
ax1.spines['bottom'].set_color(GRID_C)
ax1.yaxis.grid(True, color=GRID_C, linewidth=0.5, alpha=0.7)
ax1.set_axisbelow(True)
ax1.tick_params(axis='y', colors=SUB_C, labelsize=10)
ax1.tick_params(axis='x', colors=TEXT_C)

# secondary axis — success rate
ax2 = ax1.twinx()
ax2.set_facecolor('none')

marker_size = 110
ax2.scatter(x - w/2, ga_rate, s=marker_size, color='white', edgecolors=GA_DOT,
            linewidths=2.5, zorder=5, marker='D')
ax2.scatter(x + w/2, oc_rate, s=marker_size, color='white', edgecolors=OC_DOT,
            linewidths=2.5, zorder=5, marker='D')

# rate labels
for i in range(len(datasets)):
    ax2.annotate(f'{ga_rate[i]:.1f}%',
                 (x[i] - w/2, ga_rate[i]), textcoords="offset points",
                 xytext=(0, 12), ha='center', fontsize=11, fontweight='bold',
                 color=GA_DOT)
    ax2.annotate(f'{oc_rate[i]:.1f}%',
                 (x[i] + w/2, oc_rate[i]), textcoords="offset points",
                 xytext=(0, 12), ha='center', fontsize=11, fontweight='bold',
                 color=OC_DOT)

ax2.set_ylabel('成功率 (%)  ↑ 越高越好', fontsize=11, color=SUB_C)
ax2.set_ylim(0, 110)
ax2.spines['top'].set_visible(False)
ax2.spines['left'].set_visible(False)
ax2.spines['right'].set_color(GRID_C)
ax2.spines['bottom'].set_visible(False)
ax2.tick_params(axis='y', colors=SUB_C, labelsize=10)

# legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor=GA_BAR, edgecolor='white', alpha=0.85, label='GenericAgent — Token'),
    Patch(facecolor=OC_BAR, edgecolor='white', alpha=0.85, label='Openclaw — Token'),
    Line2D([0], [0], marker='D', color='w', markeredgecolor=GA_DOT,
           markeredgewidth=2.5, markersize=8, label='GenericAgent — 成功率'),
    Line2D([0], [0], marker='D', color='w', markeredgecolor=OC_DOT,
           markeredgewidth=2.5, markersize=8, label='Openclaw — 成功率'),
]
ax1.legend(handles=legend_elements, loc='upper left', fontsize=9.5,
           frameon=True, facecolor=BG, edgecolor=GRID_C, framealpha=0.95)

# title
fig.suptitle('GenericAgent vs Openclaw  框架效率对比',
             fontsize=16, fontweight='bold', color=TEXT_C, y=0.98)

plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(os.path.join(OUT, 'comparison.png'), dpi=200, bbox_inches='tight', facecolor=BG)
plt.close()
print('✓ comparison.png')
