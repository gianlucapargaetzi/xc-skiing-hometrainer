
def toInt16(val: int):
    val &= 0xFFFF
    if val & 0x8000:
        return val - 0x10000
    else:
        return val

def toInt32(val: int):
    val &= 0xFFFFFFFF
    if val & 0x80000000:
        return val - 0x100000000
    else:
        return val
