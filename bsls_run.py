#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test training according to params (model, task, seed, trials, rollout)
"""
import os

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf

tf.logging.set_verbosity(tf.logging.FATAL)
tf.get_logger().setLevel(3)  # is it impossible for tf to shut up?
import sys
import numpy as np
import importlib
import time
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Dense, LSTM, TimeDistributed, Input
from tensorflow.keras.utils import to_categorical
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.append(os.path.expanduser("~/gym"))
sys.path.append(os.path.expanduser("~/stable-baselines"))
sys.path.append(os.path.expanduser("~/neurogym"))
import gym
import neurogym as ngym  # need to import it so ngym envs are registered

from neurogym.utils import plotting
from neurogym.wrappers import monitor
from neurogym.wrappers import ALL_WRAPPERS
from stable_baselines.common.policies import LstmPolicy
from stable_baselines.common.vec_env import DummyVecEnv
import concurrent.futures
from custom_timings import ALL_ENVS_MINIMAL_TIMINGS
from custom_wrappers import ALL_WRAPPERS_MINIMAL_RL


def test_env(env, kwargs, num_steps=100):
    """Test if all one environment can at least be run."""
    env = gym.make(env, **kwargs)
    env.reset()
    for stp in range(num_steps):
        action = env.action_space.sample()
        state, rew, done, info = env.step(action)
        if done:
            env.reset()
    return env


def define_model(seq_len, num_h, obs_size, act_size, batch_size,
                 stateful, loss):
    """
    https://fairyonice.github.io/Stateful-LSTM-model-training-in-Keras.html
    """
    inp = Input(batch_shape=(batch_size, seq_len, obs_size), name="input")

    rnn = LSTM(num_h, return_sequences=True, stateful=stateful,
               name="RNN")(inp)

    dens = TimeDistributed(Dense(act_size, activation='softmax',
                                 name="dense"))(rnn)
    model = Model(inputs=[inp], outputs=[dens])

    model.compile(loss=loss, optimizer="Adam",  metrics=['accuracy'])

    return model


def run_env(task, task_params, main_folder, name, **train_kwargs):
    """
    task: name of task
    task_params is a dict with items:
        dt: timestep (ms, int)
        timing: duration of periods forming trial (ms)
    main_folder: main folder where the task folder will be stored
    train_kwargs: is a dict with items:
        seq_len: rollout (def: 20 timesteps, int)
        num_h: number of units (def: 256 units, int)
        steps_per_epoch: (def: 2000, int)
        batch_size: batch size
        stateful: if True network will remember state from batch to batch
    """
    folder = main_folder + task + '/'
    if not os.path.exists(folder):
        os.mkdir(folder)
    figs_folder = main_folder + '/figs/'
    if not os.path.exists(figs_folder):
        os.mkdir(figs_folder)

    training_params = {'seq_len': 20, 'num_h': 256, 'steps_per_epoch': 2000,
                       'batch_size': 64, 'stateful': True}
    training_params.update(train_kwargs)
    # Make supervised dataset
    dataset = ngym.Dataset(task, env_kwargs=task_params,
                           batch_size=training_params['batch_size'],
                           seq_len=training_params['seq_len'], cache_len=1e5)
    inputs, targets = dataset()
    env = dataset.env
    obs_size = env.observation_space.shape[0]
    act_size = env.action_space.n
    # build model
    model = define_model(seq_len=training_params['seq_len'],
                         num_h=training_params['num_h'],
                         obs_size=obs_size, act_size=act_size,
                         batch_size=training_params['batch_size'],
                         stateful=training_params['stateful'],
                         loss=task_params['loss'])
    # Train network
    data_generator = (dataset()
                      for i in range(training_params['steps_per_epoch']))
    model.fit(data_generator, verbose=1,
              steps_per_epoch=training_params['steps_per_epoch'])
    model.save_weights(folder+task+name)
    # evaluate
    model_test = define_model(seq_len=1, batch_size=1,
                              obs_size=obs_size, act_size=act_size,
                              stateful=training_params['stateful'],
                              num_h=training_params['num_h'],
                              loss=task_params['loss'])
    model_test.load_weights(folder+task+name)
    perf = eval_net_in_task(model_test, task, task_params, dataset,
                            show_fig=True, folder=figs_folder, name=name)
    return perf


def eval_net_in_task(model, env_name, kwargs, dataset, num_steps=10000,
                     show_fig=False, folder='', seed=0, n_stps_plt=100,
                     name=''):
    # run environment step by step
    if env_name == 'CVLearning-v0':
        kwargs['init_ph'] = 4
    env = gym.make(env_name, **kwargs)
    env.seed(seed=seed)
    env = monitor.Monitor(env, folder=folder, sv_per=num_steps-10,
                          sv_stp='timestep', sv_fig=show_fig, name=name)
    obs = env.reset()
    perf = []
    observations = []
    for ind_stp in range(num_steps):
        try:
            obs = env.obs_now
        except Exception:
            obs = env.obs[0]
        observations.append(obs)
        obs = obs[np.newaxis]
        obs = obs[np.newaxis]
        action = model.predict(obs)
        action = np.argmax(action, axis=-1)[0]
        _, _, _, _ = env.step(action)
    return np.mean(perf)


def apply_wrapper(env, wrap_string):
    wrap_str = ALL_WRAPPERS[wrap_string]
    wrap_module = importlib.import_module(wrap_str.split(":")[0])
    wrap_method = getattr(wrap_module, wrap_str.split(":")[1])
    return wrap_method(env, **ALL_WRAPPERS_MINIMAL_RL[wrap_string])


def train_RL(task, alg="A2C", num_trials=100000, rollout=20, dt=100,
             ntr_save=10000, n_cpu_tf=1, seed=0):
    """
    task='', alg='A2C', ntrials=100000, nrollout=20,
    ntr_save=10000, n_cpu_tf=1, seeed=0
    """
    try:
        seed = 0  # RLkwargs['seed']
        kwargs = {"dt": dt, "timing": ALL_ENVS_MINIMAL_TIMINGS[task]}
        nstps_test = 1000
        env = test_env(task, kwargs=kwargs, num_steps=nstps_test)
        TOT_TIMESTEPS = int(nstps_test * num_trials / (env.num_tr))
        OBS_SIZE = env.observation_space.shape[0]
        if isinstance(env.action_space, gym.spaces.discrete.Discrete):
            ACT_SIZE = env.action_space.n
        elif isinstance(env.action_space, gym.spaces.box.Box):
            ACT_SIZE = env.action_space.shape[0]

        savpath = os.path.expanduser(f"../trash/{alg}_{task}_{seed}/raw.npz")
        main_folder = os.path.dirname(savpath) + "/"  # savpath[:-7] + '/'

        if not os.path.exists(main_folder):
            os.makedirs(main_folder)

        if alg != "SL":
            baselines_kw = {}  # for non-common args among RL-algos
            if alg == "A2C":
                from stable_baselines import A2C as algo
            elif alg == "ACER":
                from stable_baselines import ACER as algo
            elif alg == "ACKTR":
                from stable_baselines import ACKTR as algo
            elif alg == "PPO2":
                from stable_baselines import PPO2 as algo

                baselines_kw["nminibatches"] = 1

            env = gym.make(task, **kwargs)
            env.seed(seed=seed)

            env = monitor.Monitor(
                env, folder=main_folder, sv_fig=True, num_tr_save=ntr_save
            )
            env = DummyVecEnv([lambda: env])
            model = algo(LstmPolicy, env, verbose=0, n_steps=rollout,
                         n_cpu_tf_sess=n_cpu_tf,
                         policy_kwargs={"feature_extraction": "mlp"},
                         **baselines_kw)
            model.learn(total_timesteps=TOT_TIMESTEPS)
    except Exception as e:
        print(f"failed at {task}\n{e}")


if __name__ == "__main__":
    godmode = False
    if len(sys.argv) == 2:
        if sys.argv[1] == "idkfa":
            godmode = True
    elif len(sys.argv) < 6:
        raise ValueError(
            "usage: bsls_run.py [model] [task] "
            + "[seed] [num_trials] [rollout] (wrapper1) (wrapper2) ..."
        )
    if godmode:
        godkwargs = dict(
            alg="A2C",
            seed=0,
            num_trials=100000,
            rollout=20,
            ntr_save=10000,
            dt=100,
            n_cpu_tf=1,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=7) as executor:
            for i in executor.map(train_RL, ALL_ENVS_MINIMAL_TIMINGS.keys()):
                print(f"submitted {i} jobs")
    else:
        # ARGS
        alg = sys.argv[1]  # a2c acer acktr or ppo2
        task = sys.argv[2]  # ngym task (neurogym.all_tasks.keys())
        seed = int(sys.argv[3])
        num_trials = int(sys.argv[4])
        rollout = int(sys.argv[5])  # use 20 if short periods, else 100
        if len(sys.argv) > 6:
            extra_wrap = sys.argv[6:]
        else:
            extra_wrap = []
        ntr_save = 10000
        dt = 100
        n_cpu_tf = 1  # else ppo2 crashes

    if not godmode:
        kwargs = {"dt": dt, "timing": ALL_ENVS_MINIMAL_TIMINGS[task]}

        # other relevant vars
        nstps_test = 1000
        env = test_env(task, kwargs=kwargs, num_steps=nstps_test)
        TOT_TIMESTEPS = int(nstps_test * num_trials / (env.num_tr))
        OBS_SIZE = env.observation_space.shape[0]
        if isinstance(env.action_space, gym.spaces.discrete.Discrete):
            ACT_SIZE = env.action_space.n
        elif isinstance(env.action_space, gym.spaces.box.Box):
            ACT_SIZE = env.action_space.shape[0]

        if extra_wrap:
            savpath = os.path.expanduser(
                f"../trash/{alg}_{task}_{seed}_{extra_wrap}/raw.npz"
            )
        else:
            savpath =\
                os.path.expanduser(f"../trash/{alg}_{task}_{seed}/raw.npz")
        main_folder = os.path.dirname(savpath) + "/"  # savpath[:-7] + '/'

        if not os.path.exists(main_folder):
            os.makedirs(main_folder)

        if alg != "SL":
            baselines_kw = {}  # for non-common args among RL-algos
            if alg == "A2C":
                from stable_baselines import A2C as algo
            elif alg == "ACER":
                from stable_baselines import ACER as algo
            elif alg == "ACKTR":
                from stable_baselines import ACKTR as algo
            elif alg == "PPO2":
                from stable_baselines import PPO2 as algo

                baselines_kw["nminibatches"] = 1

            env = gym.make(task, **kwargs)
            env.seed(seed=seed)
            for wrap in extra_wrap:
                env = apply_wrapper(env, wrap)
                # env = wrap_method(env, **ALL_WRAPPERS_MINIMAL_RL[extra_wrap])

            env = monitor.Monitor(
                env, folder=main_folder, sv_fig=True, num_tr_save=ntr_save
            )
            env = DummyVecEnv([lambda: env])
            model = algo(
                LstmPolicy,
                env,
                verbose=0,
                n_steps=rollout,  # no verbose :D
                n_cpu_tf_sess=n_cpu_tf,
                policy_kwargs={"feature_extraction": "mlp"},
                **baselines_kw,
            )
            model.learn(total_timesteps=TOT_TIMESTEPS)
            model.save(f"{main_folder}model")
        else:
            training_params = {'seq_len': rollout, 'num_h': 256,
                               'steps_per_epoch': 2000,
                               'batch_size': 64, 'stateful': True}
            sv_stp = 4  # save data every sv_stp epochs
            num_svs = int(training_params['steps_per_epoch']/sv_stp)
            for ind_ep in range(num_svs):
                run_env(task=task, task_params=kwargs, main_folder=main_folder,
                        name=str(ind_ep), **training_params)

    else:
        print("now should be done by concurrent.futures, previously")
