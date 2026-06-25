import matplotlib
matplotlib.use('Agg')  # 非交互式后端，避免弹窗
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

fig, ax = plt.subplots(figsize=(10, 4))
ax.set_xlim(0, 10)
ax.set_ylim(0, 4)
ax.axis('off')

boxes = [
    (1, 2, '商品数据源\n(Excel/API)'),
    (4, 2, 'AI 优化引擎\n(DeepSeek 大模型)'),
    (7, 2, '抖店开放平台 API\n(商品创建/编辑)'),
    (5.5, 0.5, 'Excel 报表导出\n(运营核查)')
]

for x, y, text in boxes:
    rect = mpatches.FancyBboxPatch((x-0.8, y-0.5), 1.6, 1,
                                   boxstyle="round,pad=0.1",
                                   facecolor='#E3F2FD', edgecolor='#1565C0', linewidth=2)
    ax.add_patch(rect)
    ax.text(x, y, text, ha='center', va='center', fontsize=9, fontweight='bold')

ax.annotate('', xy=(3.1, 2), xytext=(1.9, 2),
            arrowprops=dict(arrowstyle='->', color='#1565C0', lw=2))
ax.annotate('', xy=(6.1, 2), xytext=(4.9, 2),
            arrowprops=dict(arrowstyle='->', color='#1565C0', lw=2))
ax.annotate('', xy=(5.5, 1.2), xytext=(5.5, 1.7),
            arrowprops=dict(arrowstyle='->', color='#1565C0', lw=2))

ax.text(2.5, 2.8, '1. 商家录入\n商品信息', ha='center', fontsize=8, color='#424242')
ax.text(5.5, 2.8, '2. AI 优化标题\n生成建议售价', ha='center', fontsize=8, color='#424242')
ax.text(8.2, 2.8, '3. 批量上架\n/修改价格', ha='center', fontsize=8, color='#424242')
ax.text(5.5, -0.2, '4. 导出报表', ha='center', fontsize=8, color='#424242')

plt.tight_layout()
plt.savefig('architecture.png', dpi=200, bbox_inches='tight')
print("架构图已保存为 architecture.png")