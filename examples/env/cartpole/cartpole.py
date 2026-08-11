#!/usr/bin/python

from pathlib import Path
import collections
import json
import math
import mujoco
import mujoco.viewer
import npc_maker.env
import random
import time

# 
position_range  = 2.4
velocity_range  = 1.5
angle_range     = math.radians(36)
ang_vel_range   = math.radians(115)

# 
bias_gin     = 0
angle_gin    = 1
position_gin = 3
motor_gin    = 4

def initial_states_sweep():
    """ Perform a systematic sweep of the initial state space. """
    percents      = [-.9, -.5, 0, .5, .9]
    initial_states = []
    for a in percents:
        init_position = a * position_range
        for b in percents:
            init_angle = b * angle_range
            for c in percents:
                init_ang_vel = c * ang_vel_range
                for d in percents:
                    init_velocity = d * velocity_range
                    # 
                    initial_states.append((
                        init_position,
                        init_velocity,
                        init_angle,
                        init_ang_vel,))
    return initial_states

class CartpoleEnvironment(npc_maker.env.SoloAPI):
    def __init__(self, spec, mode, **settings):
        # Initialize the MuJoCo simulation.
        mjcf_file  = str(spec["spec"].with_suffix(".mjcf"))
        self.model = mujoco.MjModel.from_xml_path(mjcf_file)
        self.data  = mujoco.MjData(self.model)
        if mode == "graphical":
            self.viewer = mujoco.viewer.launch_passive(self.model, self.data,
                                        show_left_ui=False, show_right_ui=False)
            with self.viewer.lock():
                # TODO: This does not appear to work.
                self.viewer.cam.fixedcamid = self.data.camera("fixed").id
        else:
            self.viewer = None
        # Initialize the environment's state.
        self.dt         = self.model.opt.timestep
        self.sweep      = settings["sweep"]
        self.trials     = settings["trials"]
        self.time       = settings["time"]
        self.angle      = settings["angle"]
        if self.sweep:
            self.init   = initial_states_sweep()
            self.trials = len(self.initial_states)
            self.time   = 10
            del self.angle
        self.reset_individual()

    def reset_individual(self):
        """ Initialize the empty fields for an individual's data. """
        self.name         = None # UUID string.
        self.ctrl         = None
        self.scores       = [] # Score for each trial.
        self.survived     = [] # How many timesteps it survive in each trial.
        self.oscillations = collections.deque()

    def advance(self, name, controller):
        """ Run the environment forward one step. """
        if name != self.name:
            self.reset_individual()
            self.name = name
            self.ctrl = controller
            self.start_trial() # Reset the environment for the new individual.
        # 
        score = self.advance_environment()
        self.update_graphics()
        return score

    def start_trial(self):
        """ Prepare for a new trial. Reset the simulation and control system. """
        mujoco.mj_resetData(self.model, self.data)
        if self.ctrl is not None:
            self.ctrl.reset()
        self.num_steps = 0
        # Initialize the cart & pole positions.
        if self.sweep:
            trial_num  = len(self.scores)
            p, v, a, q = self.init[trial_num]
            self.data.joint("slider").qpos[0] = p
            self.data.joint("slider").qvel[0] = v
            self.data.joint("hinge").qpos[0]  = a
            self.data.joint("hinge").qvel[0]  = q
        else:
            angle = math.radians(self.angle)
            self.data.joint("slider").qpos[0] = 0.0
            self.data.joint("slider").qvel[0] = 0.0
            self.data.joint("hinge").qpos[0]  = random.uniform(-angle, angle)
            self.data.joint("hinge").qvel[0]  = 0.0

    def advance_controller(self, position, velocity, angle):
        """
        Run the control system. Transfer sensory inputs and motor outputs
        between the simulation and the controller.
        """
        if not self.ctrl.is_alive():
            self.quit()
        # 
        self.ctrl.set_input(bias_gin,     1.0)
        self.ctrl.set_input(angle_gin,    angle)
        self.ctrl.set_input(position_gin, position)
        # 
        self.ctrl.advance(self.dt)
        # Write the motor outputs into the mujoco simulation.
        output = float(self.ctrl.get_outputs(motor_gin))
        output = max(-1.0, min(1.0, output))
        self.data.actuator("motor").ctrl = output

    def advance_environment(self):
        # Read the cart's sensor data.
        position    = self.data.joint("slider").qpos[0]
        velocity    = self.data.joint("slider").qvel[0]
        angle       = self.data.joint("hinge").qpos[0]
        ang_vel     = self.data.joint("hinge").qvel[0]
        # Scale the sensory inputs into the range [-1, +1]
        position /= position_range
        velocity /= velocity_range
        angle    /= angle_range
        ang_vel  /= ang_vel_range
        # Run the control system.
        if self.ctrl is not None:
            self.advance_controller(position, velocity, angle)
        # Measure the magnitude of the oscillations.
        self.oscillations.append(
            abs(position) +
            abs(velocity) +
            abs(angle) +
            abs(ang_vel))
        while len(self.oscillations) > 100:
            self.oscillations.popleft()
        # Advance the mujoco simulation.
        mujoco.mj_step(self.model, self.data)
        self.num_steps += 1
        # Check if the trial is over.
        fallen_pole       = abs(angle) > 1
        runaway_cart      = abs(position) >= 1
        survived          = not (fallen_pole or runaway_cart)
        episode_time      = self.num_steps * self.dt
        timelimit_reached = episode_time >= self.time
        if not survived or timelimit_reached:
            # Determine how many timesteps the controller survived.
            if not survived:
                episode_time -= self.dt # Ignore the current timestep if it died.
            self.survived.append(episode_time)
            # Calculate the score for this trial.
            time_score = episode_time / self.time
            if len(self.oscillations) < 100:
                oscillation_score = 0
            else:
                oscillation_score = 0.75 / sum(self.oscillations)
            score = 0.1 * time_score + 0.9 * oscillation_score
            self.scores.append(score)
            # Was this the final trial? Either prepare this individual for its
            # next trial or report its final score.
            if len(self.scores) < self.trials:
                self.start_trial()
            else:
                # Report the fraction of the trials that were successful.
                successful = sum(t >= self.time for t in self.survived)
                npc_maker.env.info(self.name,
                    {"generalization": successful / self.trials})
                # Report this individual's final score.
                return sum(self.scores) / len(self.scores)

    def update_graphics(self):
        if self.viewer and self.viewer.is_running():
            # Limit the framerate to not run faster than the underlying simulation.
            if hasattr(self, "_last_frame_timestamp"):
                elapsed_time = time.monotonic() - self._last_frame_timestamp
                frame_time   = self.dt - elapsed_time
                time.sleep(max(0, frame_time))
            # 
            self.viewer.sync()
            self._last_frame_timestamp = time.monotonic()

    def quit(self):
        """ Cleanup and exit. """
        if self.viewer:
            self.viewer.close()
        self.reset_individual()
        self.model  = None
        self.data   = None
        self.viewer = None

if __name__ == "__main__":
    CartpoleEnvironment.main()
