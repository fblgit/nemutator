import string

def get_mb(mem):
    return f'{float(int(mem)>>20)}Mi'

def get_bytes(mem, suffix='k'):
    for x in range(0, len(str(mem))):
        if str(mem)[x] in string.ascii_letters:
            suffix = str(mem).lower()[x]
            size = int(str(mem)[0:x])
            break
    if suffix.lower() in ['k', 'kb', 'kib']:
        return size << 10
    if suffix.lower() in ['m', 'mi', 'mib']:
        return size << 20
    if suffix.lower() in ['g', 'gi', 'gib']:
        return size << 30
    return mem

def clean_cpu(cpu, mode='k8'):
    mult = 1
    if mode == 'prom':
        mult = 1000
    if isinstance(cpu, str):
        if 'm' in cpu:
            cpu = float(f"0.{cpu[0:-1]}")*mult
        else:
            cpu = int(cpu)*mult
    elif isinstance(cpu, int):
        cpu = float(cpu)*mult
    return int(cpu)
