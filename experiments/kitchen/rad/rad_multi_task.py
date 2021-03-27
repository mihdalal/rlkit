import argparse
import random

from rad.kitchen_train import experiment

import rlkit.util.hyperparameter as hyp
from rlkit.launchers.launcher_util import run_experiment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp_prefix", type=str, default="test")
    parser.add_argument("--num_seeds", type=int, default=1)
    parser.add_argument("--mode", type=str, default="local")
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args()
    exp_prefix = args.exp_prefix
    variant = dict(
        agent_kwargs=dict(
            discount=0.99,
            critic_lr=2e-4,
            actor_lr=2e-4,
            encoder_lr=2e-4,
            encoder_type="pixel",
            discrete_continuous_dist=False,
            data_augs="no_aug",
        ),
        num_train_steps=250000,
        frame_stack=1,
        replay_buffer_capacity=int(1e6),
        action_repeat=1,
        num_eval_episodes=5,
        init_steps=2500,
        pre_transform_image_size=64,
        image_size=64,
        batch_size=512,
        eval_freq=1000,
        log_interval=1000,
        env_kwargs=dict(
            dense=False,
            image_obs=True,
            fixed_schema=False,
            action_scale=1.4,
            use_combined_action_space=True,
            proprioception=False,
            wrist_cam_concat_with_fixed_view=False,
            use_wrist_cam=False,
            normalize_proprioception_obs=True,
            use_workspace_limits=True,
            max_steps=15,
        ),
        seed=-1,
    )

    search_space = {
        "agent_kwargs.data_augs": [
            "no_aug",
        ],
        "agent_kwargs.discrete_continuous_dist": [True, False],
        "env_kwargs.max_steps": [15],
        "env_kwargs.discount": [0.99, 0.95],
        "env_class": [
            "hinge_slide_bottom_left_burner_light",
            "microwave_kettle_light_top_left_burner",
        ],
    }
    sweeper = hyp.DeterministicHyperparameterSweeper(
        search_space,
        default_parameters=variant,
    )
    for exp_id, variant in enumerate(sweeper.iterate_hyperparameters()):
        for _ in range(args.num_seeds):
            seed = random.randint(0, 100000)
            variant["seed"] = seed
            variant["exp_id"] = exp_id
            run_experiment(
                experiment,
                exp_prefix=args.exp_prefix,
                mode=args.mode,
                variant=variant,
                use_gpu=True,
                snapshot_mode="none",
                python_cmd="~/miniconda3/envs/hrl-exp-env/bin/python",
                seed=seed,
                exp_id=exp_id,
            )
