#!/usr/bin/python

"""
Plot the logistic function.
"""

from math import exp

def logistic(value, slope=1, midpoint=0):
    # The magic number 4.0 scales the maximum slope of the curve to 1.0
    x = 4.0 * slope * (value - midpoint)
    return 1.0 / (1.0 + exp(-x) )

if __name__ == '__main__':
    import numpy as np
    import matplotlib.pyplot as plt
    import argparse
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--slope', type=float, default=1)
    args.add_argument('--midpoint', type=float, default=0)
    args = args.parse_args()
    print("logistic(0) =", logistic(0.0, args.slope, args.midpoint))
    num_pts  = 100
    radius   = 2 / args.slope
    low      = args.midpoint - radius
    high     = args.midpoint + radius
    x_coords = np.linspace( low, high, num_pts )
    plt.figure('Logistic Function')
    plt.plot(x_coords, [logistic(x, args.slope, args.midpoint) for x in x_coords])
    plt.ylim(0, 1)
    plt.show()
