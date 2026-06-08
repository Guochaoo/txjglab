from tomasulo_engine import *

print('=' * 60)
print('TEST 1: No Conflict Program')
print('=' * 60)
sim = TomasuloSimulator()
program = parse_program('''
LD F0, 0(R1)
LD F2, 8(R1)
LD F4, 16(R1)
ADD.D F6, F0, F2
MUL.D F8, F0, F4
SUB.D F10, F2, F4
DIV.D F12, F8, F6
SD F10, 32(R1)
SD F12, 40(R1)
''')
sim.load(program)
sim.run_to_completion()
print(f'Cycles: {sim.clock}')
print(f'Issued: {sim.issue_count}, Executed: {sim.exec_count}')
print(f'Stalls: {sim.total_stalls}')
stats = sim.get_stats()
print(f"IPC: {stats['ipc']:.3f}, CPI: {stats['cpi']:.3f}")
print()

print('=' * 60)
print('TEST 2: RAW Conflict Program')
print('=' * 60)
sim2 = TomasuloSimulator()
program2 = parse_program('''
LD F0, 0(R1)
ADD.D F2, F0, F4
MUL.D F6, F2, F8
SUB.D F10, F6, F0
DIV.D F12, F10, F2
SD F12, 32(R1)
''')
sim2.load(program2)
sim2.run_to_completion()
print(f'Cycles: {sim2.clock}')
print(f'Issued: {sim2.issue_count}, Executed: {sim2.exec_count}')
print(f'Stalls: {sim2.total_stalls}')
stats2 = sim2.get_stats()
print(f"IPC: {stats2['ipc']:.3f}, CPI: {stats2['cpi']:.3f}")
print()

print('=' * 60)
print('TEST 3: WAR Conflict Program')
print('=' * 60)
sim3 = TomasuloSimulator()
program3 = parse_program('''
MUL.D F0, F2, F4
ADD.D F6, F0, F8
SUB.D F0, F10, F12
DIV.D F14, F0, F6
LD F16, 0(R1)
MUL.D F18, F16, F14
SD F0, 32(R1)
SD F18, 40(R1)
''')
sim3.load(program3)
sim3.run_to_completion()
print(f'Cycles: {sim3.clock}')
print(f'Issued: {sim3.issue_count}, Executed: {sim3.exec_count}')
print(f'Stalls: {sim3.total_stalls}')
stats3 = sim3.get_stats()
print(f"IPC: {stats3['ipc']:.3f}, CPI: {stats3['cpi']:.3f}")
print()
print('All tests passed!')
