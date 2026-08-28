#!/usr/bin/python
"""
A very simple PID controller for testing the Cartpole environment.
"""
import npc_maker.ctrl
import npc_maker.env
import pid

env_spec, population = npc_maker.ctrl.get_args()
env_spec    = npc_maker.env.Specification(env_spec)
interfaces  = env_spec["populations"][0]["interfaces"]
interfaces  = {x["name"]: x["gin"] for x in interfaces}
pole_gin    = interfaces["Pole Angle"]
cart_gin    = interfaces["Cart Position"]
motor_gin   = interfaces["Motor Output"]

dt = 0.01

class PidController(npc_maker.ctrl.API):
    def new(self, genome):
        genome  = {chromosome["name"]: chromosome for chromosome in genome}
        args    = genome[pole_gin]
        self.pole_pid = pid.Controller()
        pid_args = pid.Parameters()
        pid_args.kp = args["kp"]
        pid_args.ki = args["ki"]
        pid_args.kd = args["kd"]
        self.pole_pid.new(pid_args)

    def reset(self):
        self.pole_pid.reset()

    def set_input(self, gin, value):
        if gin == pole_gin:
            self.pole_pid.set_input(0, float(value))

    def get_output(self, gin):
        return -float(self.pole_pid.get_output(0))

    def advance(self, dt):
        self.output = self.pole_pid.advance(dt)

pid_controller = PidController()
npc_maker.ctrl.main(pid_controller)
