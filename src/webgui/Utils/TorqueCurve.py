import numpy as np
from typing import Tuple

def A(x0, x1, xk):
    return  np.array([  [x0**2, x0,     1,      0,      0,      0],
                        [2*x0,  1,      0,      0,      0,      0],
                        [0,     0,      0,      x1**2,  x1,     1],
                        [0,     0,      0,      2*x1,   1,      0],
                        [xk**2, xk,     1,      -(xk**2), -xk, -1],
                        [2*xk,  1,      0,      -2*xk, -1,      0]]     )

def b(y0, y1):
    return np.array([[y0],
                    [0],
                    [y1],
                    [0],
                    [0],
                    [0]])

def createTorqueCurve(ease_in: float, ease_out: float, xkrit: float, y0: float, y1: float, len=1000, relative = True) -> Tuple[np.ndarray, np.ndarray]:
    """Create a Torque curve with ease in and ease out around xkirt. 
        The ease in starts at (xkrit - ease_in) * len and the ease out ends at (xkrit + ease_out) * len


    Args:
        ease_in (float): relative length of total length for ease in
        ease_out (float): relative length of total lenfth for ease out
        xkrit (float): relativ length of total length where easing is centered
        y0 (float): start value for x < (xkrit - ease_in) * len
        y1 (float): end value for x > (xkrit + ease_out) * len
        len (int, optional): Length of output array. Defaults to 1000.
        relative (bool, optional): Wether values should be interpreted as realtive from whole intervall. Defaults to True
        

    Raises:
        ValueError: When xkrit - ease_in or xkrit + ease_out exceeds array boundary

    Returns:
        np.ndarray: Lookup table
    """

    if relative:
        xkrit = int(xkrit * len)
        ease_in = int(ease_in * len)
        ease_out = int(ease_out * len)
    
    if (xkrit - ease_in < 0 or xkrit + ease_out >= len):
        raise ValueError


    a = A(xkrit-ease_in, xkrit +ease_out, xkrit)
    B = b(y0, y1)

    param = np.linalg.solve(a,B)

    values = np.zeros(len)
    x = np.arange(0, len, 1)
    values[0:xkrit-ease_in] = y0
    values[xkrit+ease_out:] = y1
    ease_in_vals = param[0]*x**2 +param[1]*x +param[2]
    ease_out_vals = param[3]*x**2 +param[4]*x +param[5]

    values[xkrit-ease_in    :       xkrit]              = ease_in_vals[xkrit-ease_in            : xkrit]
    values[xkrit            :       xkrit+ ease_out]    = ease_out_vals[xkrit                   : xkrit+ease_out]
    
    # print(np.shape(x), np.shape(values))

    return x,values