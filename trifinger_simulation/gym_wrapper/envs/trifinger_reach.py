import math
import numpy as np
import time
import datetime

import gym

from trifinger_simulation.sim_finger import SimFinger
from trifinger_simulation.gym_wrapper.data_logger import DataLogger
from trifinger_simulation.gym_wrapper.finger_spaces import FingerSpaces
from trifinger_simulation.gym_wrapper import utils
from trifinger_simulation import visual_objects, sample, finger_types_data


class TriFingerReach(gym.Env):
    """
    A gym environment to enable training on either the single or
    the tri-fingers robots for the task of reaching
    """

    def __init__(
        self,
        control_rate_s,
        finger_type,
        enable_visualization,
        smoothing_params,
        use_real_robot=False,
        finger_config_suffix="0",
        synchronize=False,
    ):
        """Intializes the constituents of the reaching environment.

        Constructor sets up the finger robot depending on the finger type, and
        also whether an instance of the simulated or the real robot is to be
        created. Also sets up the observation and action spaces, smoothing for
        reducing jitter on the robot, and provides for a way to synchronize
        robots being trained independently.

        Args:
            control_rate_s (float): the rate (in seconds) at which step method of the env
                will run. The actual robot controller may run at a higher rate,
                so this is used to compute the number of robot control updates
                per environment step.
            finger_type (string): Name of the finger type.  In order to get
                a dictionary of the valid finger types, call
                :meth:`.finger_types_data.get_valid_finger_types`
            enable_visualization (bool): if the simulation env is to be
                visualized
            smoothing_params (dict):
                num_episodes (int): the total number of episodes for which the
                    training is performed
                start_after (float): the fraction of episodes after which the
                    smoothing of applied actions to the motors should start
                final_alpha (float): smoothing coeff that will be reached at
                    the end of the smoothing
                stop_after (float): the fraction of total episodes by which
                    final alpha is to be reached, after which the same final
                    alpha will be used for smoothing in the remainder of
                    the episodes
                is_test (bool, optional): Include this for testing
            use_real_robot (bool): if training is to be performed on
                the real robot ([default] False)
            finger_config_suffix: pass this if only one of
                the three fingers is to be trained. Valid choices include
                [0, 120, 240] ([default] 0)
            synchronize (bool): Set this to True if you want to train
                independently on three fingers in separate processes, but
                have them synchronized. ([default] False)
        """
        #: an instance of a simulated, or a real robot depending on
        #: what is desired.
        if use_real_robot:
            from pybullet_fingers.real_finger import RealFinger

            self.finger = RealFinger(
                finger_type=finger_type,
                finger_config_suffix=finger_config_suffix,
                enable_visualization=enable_visualization,
            )

        else:
            self.finger = SimFinger(
                finger_type=finger_type,
                enable_visualization=enable_visualization,
            )

        self.num_fingers = finger_types_data.get_number_of_fingers(finger_type)

        #: the number of times the same action is to be applied to
        #: the robot.
        self.steps_per_control = int(
            round(control_rate_s / self.finger.time_step_s)
        )
        assert (
            abs(
                control_rate_s
                - self.steps_per_control * self.finger.time_step_s
            )
            <= 0.000001
        )

        #: the types of observations that should be a part of the environment's
        #: observed state
        self.observations_keys = [
            "joint_positions",
            "joint_velocities",
            "goal_position",
            "action_joint_positions",
        ]

        self.observations_sizes = [
            3 * self.num_fingers,
            3 * self.num_fingers,
            3 * self.num_fingers,
            3 * self.num_fingers,
        ]

        # sets up the observation and action spaces for the environment,
        # unscaled spaces have the custom bounds set up for each observation
        # or action type, whereas all the values in the observation and action
        # spaces lie between 1 and -1
        self.spaces = FingerSpaces(
            num_fingers=self.num_fingers,
            observations_keys=self.observations_keys,
            observations_sizes=self.observations_sizes,
            separate_goals=True,
        )

        self.unscaled_observation_space = (
            self.spaces.get_unscaled_observation_space()
        )
        self.unscaled_action_space = self.spaces.get_unscaled_action_space()

        self.observation_space = self.spaces.get_scaled_observation_space()
        self.action_space = self.spaces.get_scaled_action_space()

        #: a logger to enable logging of observations if desired
        self.logger = DataLogger()

        # sets up smoothing
        if "is_test" in smoothing_params:
            self.smoothing_start_episode = 0
            self.smoothing_alpha = smoothing_params["final_alpha"]
            self.smoothing_increase_step = 0
            self.smoothing_stop_episode = math.inf
        else:
            self.smoothing_stop_episode = int(
                smoothing_params["num_episodes"]
                * smoothing_params["stop_after"]
            )

            self.smoothing_start_episode = int(
                smoothing_params["num_episodes"]
                * smoothing_params["start_after"]
            )
            num_smoothing_increase_steps = (
                self.smoothing_stop_episode - self.smoothing_start_episode
            )
            self.smoothing_alpha = 0
            self.smoothing_increase_step = (
                smoothing_params["final_alpha"] / num_smoothing_increase_steps
            )

        self.smoothed_action = None
        self.episode_count = 0

        #: a marker to visualize where the target goal position for the episode
        #: is to which the tip link(s) of the robot should reach
        self.enable_visualization = enable_visualization
        if self.enable_visualization:
            self.goal_marker = visual_objects.Marker(
                number_of_goals=self.num_fingers
            )

        # set up synchronization if it's set to true
        self.synchronize = synchronize
        if synchronize:
            now = datetime.datetime.now()
            self.next_start_time = datetime.datetime(
                now.year, now.month, now.day, now.hour, now.minute + 1
            )
        else:
            self.next_start_time = None

        self.seed()
        self.reset()

    def _compute_reward(self, observation, goal):
        """
        The reward function of the environment

        Args:
            observation (list): the observation at the
                current step
            goal (list): the desired goal for the episode

        Returns:
            the reward, and the done signal
        """
        joint_positions = observation[
            self.spaces.key_to_index["joint_positions"]
        ]

        end_effector_positions = self.finger.kinematics.forward_kinematics(
            np.array(joint_positions)
        )

        # TODO is matrix norm really always same as vector norm on flattend
        # matrices?
        distance_to_goal = utils.compute_distance(end_effector_positions, goal)

        reward = -distance_to_goal
        done = False

        return reward * self.steps_per_control, done

    def _get_state(self, observation, action, log_observation=False):
        """
        Get the current observation from the env for the agent

        Args:
            log_observation (bool): specify whether you want to
                log the observation

        Returns:
            observation (list): comprising of the observations corresponding
                to the key values in the observation_keys
        """
        tip_positions = self.finger.kinematics.forward_kinematics(
            observation.position
        )
        end_effector_position = np.concatenate(tip_positions)
        joint_positions = observation.position
        joint_velocities = observation.velocity
        flat_goals = np.concatenate(self.goal)
        end_effector_to_goal = list(
            np.subtract(flat_goals, end_effector_position)
        )

        # populate this observation dict from which you can select which
        # observation types to finally choose depending on the keys
        # used for constructing the observation space of the environment
        observation_dict = {}
        observation_dict["end_effector_position"] = end_effector_position
        observation_dict["joint_positions"] = joint_positions
        observation_dict["joint_velocities"] = joint_velocities
        observation_dict["end_effector_to_goal"] = end_effector_to_goal
        observation_dict["goal_position"] = flat_goals
        observation_dict["action_joint_positions"] = action

        if log_observation:
            self.logger.append(
                joint_positions, end_effector_position, time.time()
            )

        # returns only the observations corresponding to the keys that were
        # used for constructing the observation space
        observation = [
            v for key in self.observations_keys for v in observation_dict[key]
        ]

        return observation

    def step(self, action):
        """
        The env step method

        Args:
            action (list): the joint positions that have to be achieved

        Returns:
            the observation scaled to lie between [-1;1], the reward,
            the done signal, and info on if the agent was successful at
            the current step
        """
        # Unscale the action to the ranges of the action space of the
        # environment, explicitly (as the prediction from the network
        # lies in the range [-1;1])
        unscaled_action = utils.unscale(action, self.unscaled_action_space)

        # smooth the action by taking a weighted average with the previous
        # action, where the weight, ie, the smoothing_alpha is gradually
        # increased at every episode reset (see the reset method for details)
        if self.smoothed_action is None:
            # start with current position
            # self.smoothed_action = self.finger.observation.position
            self.smoothed_action = unscaled_action

        self.smoothed_action = (
            self.smoothing_alpha * self.smoothed_action
            + (1 - self.smoothing_alpha) * unscaled_action
        )

        # this is the control loop to send the actions for a few timesteps
        # which depends on the actual control rate
        finger_action = self.finger.Action(position=self.smoothed_action)
        state = None
        for _ in range(self.steps_per_control):
            t = self.finger.append_desired_action(finger_action)
            observation = self.finger.get_observation(t)
            # get observation from first iteration (when action is applied the
            # first time)
            if state is None:
                state = self._get_state(
                    observation, self.smoothed_action, True
                )
            if self.synchronize:
                self.observation = observation
        reward, done = self._compute_reward(state, self.goal)
        info = {"is_success": np.float32(done)}
        scaled_observation = utils.scale(
            state, self.unscaled_observation_space
        )
        return scaled_observation, reward, done, info

    def reset(self):
        """
        Episode reset

        Returns:
            the scaled to [-1;1] observation from the env after the reset
        """
        # synchronize episode starts with wall time
        # (freeze the robot at the current position before starting the sleep)
        if self.next_start_time:
            try:
                t = self.finger.append_desired_action(
                    self.finger.Action(position=self.observation.position)
                )
                self.finger.get_observation(t)
            except Exception:
                pass

            utils.sleep_until(self.next_start_time)
            self.next_start_time += datetime.timedelta(seconds=4)

        # updates smoothing parameters
        self.update_smoothing()
        self.episode_count += 1
        self.smoothed_action = None

        # resets the finger to a random position
        action = sample.feasible_random_joint_positions_for_reaching(
            self.finger, self.spaces.action_bounds
        )
        observation = self.finger.reset_finger_positions_and_velocities(action)

        # generates a random goal for the next episode
        target_joint_config = np.asarray(
            sample.feasible_random_joint_positions_for_reaching(
                self.finger, self.spaces.action_bounds
            )
        )
        self.goal = self.finger.kinematics.forward_kinematics(
            target_joint_config
        )

        if self.enable_visualization:
            self.goal_marker.set_state(self.goal)

        # logs relevant information for replayability
        self.logger.new_episode(target_joint_config, self.goal)

        return utils.scale(
            self._get_state(observation, action=action),
            self.unscaled_observation_space,
        )

    def update_smoothing(self):
        """
        Update the smoothing coefficient with which the action to be
        applied is smoothed
        """
        if (
            self.smoothing_start_episode
            <= self.episode_count
            < self.smoothing_stop_episode
        ):
            self.smoothing_alpha += self.smoothing_increase_step
        print(
            "episode: {}, smoothing: {}".format(
                self.episode_count, self.smoothing_alpha
            )
        )
