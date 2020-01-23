#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 17 14:59:08 2020

@author: molano
"""
import gym
import neurogym
import numpy as np
import matplotlib.pyplot as plt
from neurogym.meta import tasks_info
from stable_baselines.common.policies import LstmPolicy
from stable_baselines.common.vec_env import DummyVecEnv
from stable_baselines import A2C  # ACER, PPO2
task = 'RDM-v0'
KWARGS = {'dt': 100, 'timing': {'fixation': ('constant', 200),
                                'stimulus': ('constant', 500),
                                'decision': ('constant', 200)}}

env = gym.make('RDM-v0')
# Optional: PPO2 requires a vectorized environment to run
# the env is now wrapped automatically when passing it to the constructor
env = DummyVecEnv([lambda: env])

model = A2C(LstmPolicy, env, verbose=1,
            policy_kwargs={'feature_extraction': "mlp"})
model.learn(total_timesteps=10000, log_interval=1000)
env.close()
data = tasks_info.plot_struct(task, num_steps_env=1000, n_stps_plt=200,
                              model=model, name=task)

states = data['states']
actions_end_of_trial = data['actions_end_of_trial']
observations = data['obs']
evidence = data['obs_cum']

end_of_trial = np.where(actions_end_of_trial != -1)


plt.figure()




