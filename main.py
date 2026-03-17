import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import itertools

# ==========================================
# 0. 底层硬件生成: 普通六边形阵列 (Regular Hexagon)
# ==========================================
def build_regular_hexagon_graph(hex_cols=3, hex_rows=2):
    G_hex = nx.hexagonal_lattice_graph(hex_rows, hex_cols, periodic=False)
    G = nx.Graph()
    node_list = list(G_hex.nodes())
    
    for idx, node in enumerate(node_list):
        real_x, real_y = G_hex.nodes[node]['pos']
        # 放大坐标比例，避免画图时挤在一起
        G.add_node(idx, pos=(real_x * 2.0, real_y * 2.0), role='unused', syndrome_type=None)
        
    for u, v in G_hex.edges():
        G.add_edge(node_list.index(u), node_list.index(v))
        
    return G

# ==========================================
# 1. Algorithm 1: Data Qubit Allocator (修复边界漏洞)
# ==========================================
def algorithm_4_1_data_allocation(G):
    print("\n" + "="*50)
    print(f"🚀 [Algorithm 1] Data Qubit Allocation (严格逻辑 + 边界回退)")
    
    # 获取 3度和4度的高连通度节点
    L_h = [n for n in G.nodes() if G.degree(n) in (3, 4)]
    
    # 构建 Bridge Rectangles (用节点集合表示以避免浮点坐标误差)
    bridge_rects = []
    for n_a in L_h:
        nodes = {n_a}
        nodes.update(G.neighbors(n_a))
        if G.degree(n_a) == 3:
            other_L_h = [n for n in L_h if n != n_a]
            if other_L_h:
                n_b = min(other_L_h, key=lambda n: nx.shortest_path_length(G, n_a, n))
                nodes.add(n_b)
                nodes.update(G.neighbors(n_b))
        
        # 避免重复添加相同的矩形区域
        if not any(r['nodes'] == nodes for r in bridge_rects):
            bridge_rects.append({'nodes': nodes})
            
    data_layout = []
    assigned_nodes = set()
    
    # 依次尝试 4个、3个、2个 互相兼容的矩形包围圈，以处理论文提到的 Boundary 问题
    for num_rects in [4, 3, 2]:
        for combo in itertools.combinations(bridge_rects, num_rects):
            # 检查是否 Mutually Compatible (重叠面积为 0, 即节点集互不相交)
            is_compatible = True
            for r1, r2 in itertools.combinations(combo, 2):
                if not r1['nodes'].isdisjoint(r2['nodes']):
                    is_compatible = False
                    break
                    
            if is_compatible:
                # 提取被包围的潜在数据区 (与这些矩形都相邻，但不在它们内部的节点)
                all_rect_nodes = set().union(*(r['nodes'] for r in combo))
                potent_dqbits = []
                
                for n in G.nodes():
                    if n in all_rect_nodes or n in assigned_nodes:
                        continue
                    
                    # 如果节点距离所有被选中的矩形核心都很近，说明它处于包围网中
                    if all(any(nx.shortest_path_length(G, n, rn) <= 2 for rn in r['nodes']) for r in combo):
                        potent_dqbits.append(n)
                        
                if potent_dqbits:
                    # 取几何中心点
                    avg_x = sum(G.nodes[n]['pos'][0] for n in potent_dqbits) / len(potent_dqbits)
                    avg_y = sum(G.nodes[n]['pos'][1] for n in potent_dqbits) / len(potent_dqbits)
                    dqb = min(potent_dqbits, key=lambda n: (G.nodes[n]['pos'][0] - avg_x)**2 + (G.nodes[n]['pos'][1] - avg_y)**2)
                    
                    # 确保新加入的 Data Qubit 不会和已有的靠得太近 (距离至少为2)
                    if not any(nx.shortest_path_length(G, dqb, exist_dq) <= 2 for exist_dq in data_layout):
                        data_layout.append(dqb)
                        assigned_nodes.add(dqb)
                        G.nodes[dqb]['role'] = 'data'
                    
    print(f"✅ 定位 Data Qubits 共 {len(data_layout)} 个: {data_layout}")
    return data_layout

# ==========================================
# 2. Algorithm 2: Bridge Tree Finder
# ==========================================
def algorithm_4_2_bridge_tree_finder(G, data_qubits):
    print("\n" + "="*50)
    print("🚀 [Algorithm 2] Bridge Tree Construction")
    
    if not data_qubits: return []

    syndrome_groups = []
    unassigned_dq = set(data_qubits)
    
    group_id = 0
    while len(unassigned_dq) >= 2:
        start_dq = unassigned_dq.pop()
        distances = {dq: nx.shortest_path_length(G, source=start_dq, target=dq) for dq in unassigned_dq}
        closest = sorted(distances, key=distances.get)[:3]
        
        targets = [start_dq] + closest
        for t in closest:
            unassigned_dq.remove(t)
            
        syndrome_groups.append({
            'id': f'Syndrome_{group_id}',
            'type': 'X' if group_id % 2 == 0 else 'Z', 
            'targets': targets
        })
        group_id += 1

    candidate_trees = []
    
    for sg in syndrome_groups:
        targets = sg['targets']
        best_tree = None
        min_edges = 999
        
        for qb in G.nodes():
            if G.nodes[qb].get('role') == 'data': continue
            
            tree_edges = set()
            tree_depth = 0
            valid = True
            
            for t in targets:
                try:
                    path = nx.shortest_path(G, source=qb, target=t)
                    depth = len(path) - 1
                    if depth > tree_depth: tree_depth = depth
                    
                    for idx in range(len(path)-1):
                        if G.nodes[path[idx]]['role'] == 'data' and path[idx] not in targets:
                            valid = False
                        tree_edges.add((path[idx], path[idx+1]))
                except nx.NetworkXNoPath:
                    valid = False
            
            if valid and len(tree_edges) < min_edges:
                min_edges = len(tree_edges)
                best_tree = {
                    'id': sg['id'], 'type': sg['type'],
                    'center': qb, 'edges': tree_edges, 'depth': tree_depth, 'targets': targets
                }
                
        if best_tree:
            candidate_trees.append(best_tree)
            G.nodes[best_tree['center']]['role'] = 'ancillary'
            G.nodes[best_tree['center']]['syndrome_type'] = best_tree['type']
            
            for u, v in best_tree['edges']:
                if G.nodes[u].get('role') != 'data': G.nodes[u]['role'] = 'ancillary'
                if G.nodes[v].get('role') != 'data': G.nodes[v]['role'] = 'ancillary'
            
    print(f"✅ 成功构建了 {len(candidate_trees)} 棵局部最短桥接树。")
    return candidate_trees

# ==========================================
# 3. Algorithm 3: Stabilizer Scheduler 
# ==========================================
def algorithm_4_3_measurement_scheduler(candidate_trees):
    print("\n" + "="*50)
    print("🚀 [Algorithm 3] Iterative Measurement Scheduling")
    
    if not candidate_trees: return
        
    S1 = [t for t in candidate_trees if t['type'] == 'X']
    S2 = [t for t in candidate_trees if t['type'] == 'Z']
    
    def exec_time(schedule):
        return max([t['depth'] for t in schedule]) if schedule else 0

    time_S1 = exec_time(S1)
    time_S2 = exec_time(S2)
    
    print(f"   -> 当前调度策略:")
    print(f"   🕐 第一批次 (X 并行) 最大耗时: {time_S1} 步")
    print(f"   🕐 第二批次 (Z 并行) 最大耗时: {time_S2} 步")
    print(f"   🏁 一轮纠错总耗时: {time_S1 + time_S2} 步")
    print("=" * 50 + "\n")

# ==========================================
# 4. 出图函数
# ==========================================
def save_compiled_graph(G, filename="surf_stitch_3x2_fixed.png"):
    pos = nx.get_node_attributes(G, 'pos')
    
    color_map = {
        'data': '#0070C0',      
        'ancillary': '#FF0000', 
        'unused': '#E0E0E0'     
    }
    node_colors = [color_map.get(G.nodes[n].get('role', 'unused'), '#E0E0E0') for n in G.nodes()]
    
    labels = {}
    for n in G.nodes():
        role = G.nodes[n].get('role')
        syndrome = G.nodes[n].get('syndrome_type')
        
        if role == 'data':
            labels[n] = str(n)  
        elif role == 'ancillary' and syndrome in ['X', 'Z']:
            labels[n] = syndrome 
        else:
            labels[n] = ''      

    plt.figure(figsize=(12, 6))
    nx.draw_networkx_edges(G, pos, edge_color='gray', width=1.5, alpha=0.5)
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=600, edgecolors='white')
    nx.draw_networkx_labels(G, pos, labels=labels, font_color='white', font_weight='bold', font_size=10)
    
    legend_handles = [
        mpatches.Patch(color='#0070C0', label='Data Qubit'),
        mpatches.Patch(color='#FF0000', label='Syndrome Root (X/Z) & Bridge'),
        mpatches.Patch(color='#E0E0E0', label='Unused Qubit')
    ]
    plt.legend(handles=legend_handles, loc='upper right', bbox_to_anchor=(1.15, 1), fontsize=10)
    plt.title(f"Surf-Stitch Implementation (Fixed Algorithm 1)", fontsize=16)
    plt.axis('equal')
    plt.axis('off') 
    plt.tight_layout()
    
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📷 完工！图片已保存至: {filename}")


if __name__ == "__main__":
    hexagon_columns = 3
    hexagon_rows = 2
    
    device_graph = build_regular_hexagon_graph(hex_cols=hexagon_columns, hex_rows=hexagon_rows)
    data_qubits = algorithm_4_1_data_allocation(device_graph)
    candidate_trees = algorithm_4_2_bridge_tree_finder(device_graph, data_qubits)
    algorithm_4_3_measurement_scheduler(candidate_trees)
    
    save_compiled_graph(device_graph, filename="surf_stitch_3x2_fixed.png")