#!/usr/bin/env python

from npc_maker import env

def main():
    while True:
        env.spawn()
        indiv = env.input()
        score = 1/0
        env.score(indiv.name, score)
        env.death(indiv.name)
