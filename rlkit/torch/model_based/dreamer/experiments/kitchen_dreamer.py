def experiment(variant):
    import os

    import gym

    os.environ["D4RL_SUPPRESS_IMPORT_ERROR"] = "1"

    import torch

    import rlkit.torch.pytorch_util as ptu
    from rlkit.envs.mujoco_vec_wrappers import (
        DummyVecEnv,
        StableBaselinesVecEnv,
        make_kitchen_env,
        make_metaworld_env,
    )
    from rlkit.envs.primitives_wrappers import (
        ActionRepeat,
        ImageEnvMetaworld,
        NormalizeActions,
        TimeLimit,
    )
    from rlkit.torch.model_based.dreamer.actor_models import (
        ActorModel,
        ConditionalActorModel,
    )
    from rlkit.torch.model_based.dreamer.dreamer import DreamerTrainer
    from rlkit.torch.model_based.dreamer.dreamer_policy import (
        ActionSpaceSamplePolicy,
        DreamerPolicy,
    )
    from rlkit.torch.model_based.dreamer.dreamer_v2 import DreamerV2Trainer
    from rlkit.torch.model_based.dreamer.dreamer_v2_mcts import DreamerV2MCTSTrainer
    from rlkit.torch.model_based.dreamer.episode_replay_buffer import (
        EpisodeReplayBuffer,
    )
    from rlkit.torch.model_based.dreamer.kitchen_video_func import video_post_epoch_func
    from rlkit.torch.model_based.dreamer.mlp import Mlp
    from rlkit.torch.model_based.dreamer.path_collector import VecMdpPathCollector
    from rlkit.torch.model_based.dreamer.world_models import (
        StateConcatObsWorldModel,
        WorldModel,
    )
    from rlkit.torch.model_based.plan2explore.actor_models import (
        ConditionalContinuousActorModel,
    )
    from rlkit.torch.model_based.plan2explore.mcts_policy import (
        HybridAdvancedMCTSPolicy,
    )
    from rlkit.torch.torch_rl_algorithm import TorchBatchRLAlgorithm

    gym.logger.set_level(40)
    env_suite = variant.get("env_suite", "kitchen")
    env_class = variant["env_class"]
    env_kwargs = variant["env_kwargs"]
    use_raw_actions = variant["use_raw_actions"]
    num_expl_envs = variant["num_expl_envs"]
    actor_model_class_name = variant.get("actor_model_class", "actor_model")

    if env_suite == "metaworld":
        env_fns = [
            lambda: TimeLimit(
                ImageEnvMetaworld(
                    make_metaworld_env(env_class, env_kwargs),
                    imwidth=64,
                    imheight=64,
                ),
                variant["algorithm_kwargs"]["max_path_length"],
            )
            for _ in range(num_expl_envs)
        ]
        expl_env = StableBaselinesVecEnv(env_fns=env_fns, start_method="fork")
        eval_envs = [
            TimeLimit(
                ImageEnvMetaworld(
                    make_metaworld_env(env_class, env_kwargs),
                    imwidth=64,
                    imheight=64,
                ),
                variant["algorithm_kwargs"]["max_path_length"],
            )
        ]
        eval_env = DummyVecEnv(eval_envs, pass_render_kwargs=False)
        if use_raw_actions:
            discrete_continuous_dist = False
            continuous_action_dim = eval_env.action_space.low.size
            discrete_action_dim = 0
            use_batch_length = True
        else:
            discrete_continuous_dist = variant["actor_kwargs"][
                "discrete_continuous_dist"
            ]
            continuous_action_dim = eval_envs[0].max_arg_len
            discrete_action_dim = eval_envs[0].num_primitives
            use_batch_length = False
        world_model_class = WorldModel
        action_dim = eval_env.action_space.low.size
    else:
        if use_raw_actions:
            env_fns = [
                lambda: TimeLimit(
                    NormalizeActions(
                        ActionRepeat(
                            make_kitchen_env(
                                env_class=env_class,
                                env_kwargs=variant["env_kwargs"],
                            ),
                            2,
                        )
                    ),
                    500,
                )
                for _ in range(variant["num_expl_envs"])
            ]
            expl_env = StableBaselinesVecEnv(env_fns=env_fns, start_method="fork")

            eval_envs = [
                TimeLimit(
                    NormalizeActions(
                        ActionRepeat(
                            make_kitchen_env(
                                env_class=env_class,
                                env_kwargs=variant["env_kwargs"],
                            ),
                            2,
                        )
                    ),
                    500,
                )
            ]
            eval_env = DummyVecEnv(eval_envs, pass_render_kwargs=False)
            action_dim = expl_env.action_space.low.size
            continuous_action_dim = eval_env.action_space.low.size
            discrete_action_dim = 0
            discrete_continuous_dist = False
            world_model_class = WorldModel
            use_batch_length = True
        else:
            env_fns = [
                lambda: make_kitchen_env(
                    env_class=env_class,
                    env_kwargs=variant["env_kwargs"],
                )
                for _ in range(variant["num_expl_envs"])
            ]
            expl_env = StableBaselinesVecEnv(env_fns=env_fns, start_method="fork")

            eval_envs = [
                make_kitchen_env(
                    env_class=env_class,
                    env_kwargs=variant["env_kwargs"],
                )
            ]

            eval_env = DummyVecEnv(eval_envs)

            action_dim = expl_env.action_space.low.size
            num_primitives = eval_envs[0].num_primitives
            max_arg_len = eval_envs[0].max_arg_len
            discrete_continuous_dist = variant["actor_kwargs"][
                "discrete_continuous_dist"
            ] and (not variant["env_kwargs"]["fixed_schema"])
            if (
                variant["actor_kwargs"]["discrete_continuous_dist"]
                or variant["env_kwargs"]["fixed_schema"]
                or actor_model_class_name == "continuous_conditional_actor_model"
            ):
                continuous_action_dim = max_arg_len
                discrete_action_dim = num_primitives
            else:
                continuous_action_dim = max_arg_len + num_primitives
                discrete_action_dim = 0

            if (
                variant.get("world_model_class", "world_model") == "multitask"
                or eval_envs[0].proprioception
            ):
                world_model_class = StateConcatObsWorldModel
                if eval_envs[0].proprioception:
                    variant["model_kwargs"]["embedding_size"] += variant[
                        "model_kwargs"
                    ]["state_output_size"]
            else:
                world_model_class = WorldModel
            use_batch_length = False
    obs_dim = expl_env.observation_space.low.size
    if actor_model_class_name == "conditional_actor_model":
        actor_model_class = ConditionalActorModel
    elif actor_model_class_name == "continuous_conditional_actor_model":
        actor_model_class = ConditionalContinuousActorModel
    elif actor_model_class_name == "actor_model":
        actor_model_class = ActorModel
    if variant.get("load_from_path", False):
        data = torch.load(variant["models_path"] + variant["pkl_file_name"])
        actor = data["trainer/actor"]
        vf = data["trainer/vf"]
        target_vf = data["trainer/target_vf"]
        world_model = data["trainer/world_model"]
    else:
        world_model = world_model_class(
            action_dim,
            image_shape=eval_envs[0].image_shape,
            **variant["model_kwargs"],
            env=eval_envs[0],
        )
    if variant.get("retrain_actor_and_vf", True):
        actor = actor_model_class(
            variant["model_kwargs"]["model_hidden_size"],
            world_model.feature_size,
            hidden_activation=torch.nn.functional.elu,
            discrete_action_dim=discrete_action_dim,
            continuous_action_dim=continuous_action_dim,
            env=eval_envs[0],
            **variant["actor_kwargs"],
        )
        vf = Mlp(
            hidden_sizes=[variant["model_kwargs"]["model_hidden_size"]]
            * variant["vf_kwargs"]["num_layers"],
            output_size=1,
            input_size=world_model.feature_size,
            hidden_activation=torch.nn.functional.elu,
        )
        target_vf = Mlp(
            hidden_sizes=[variant["model_kwargs"]["model_hidden_size"]]
            * variant["vf_kwargs"]["num_layers"],
            output_size=1,
            input_size=world_model.feature_size,
            hidden_activation=torch.nn.functional.elu,
        )

    if variant.get("use_mcts_policy", False):
        expl_policy = HybridAdvancedMCTSPolicy(
            world_model,
            discrete_action_dim,
            action_dim,
            eval_envs[0].action_space,
            actor,
            None,
            vf,
            **variant["expl_policy_kwargs"],
        )
        eval_policy = HybridAdvancedMCTSPolicy(
            world_model,
            discrete_action_dim,
            action_dim,
            eval_envs[0].action_space,
            actor,
            None,
            vf,
            **variant["eval_policy_kwargs"],
        )
    else:
        expl_policy = DreamerPolicy(
            world_model,
            actor,
            obs_dim,
            action_dim,
            exploration=True,
            expl_amount=variant.get("expl_amount", 0.3),
            discrete_action_dim=discrete_action_dim,
            continuous_action_dim=continuous_action_dim,
            discrete_continuous_dist=discrete_continuous_dist,
        )
        eval_policy = DreamerPolicy(
            world_model,
            actor,
            obs_dim,
            action_dim,
            exploration=False,
            expl_amount=0.0,
            discrete_action_dim=discrete_action_dim,
            continuous_action_dim=continuous_action_dim,
            discrete_continuous_dist=discrete_continuous_dist,
        )

    rand_policy = ActionSpaceSamplePolicy(expl_env)

    expl_path_collector = VecMdpPathCollector(
        expl_env,
        expl_policy,
        save_env_in_snapshot=False,
        env_params=env_kwargs,
        env_class=env_class,
    )

    eval_path_collector = VecMdpPathCollector(
        eval_env,
        eval_policy,
        save_env_in_snapshot=False,
        env_params=env_kwargs,
        env_class=env_class,
    )

    replay_buffer = EpisodeReplayBuffer(
        variant["replay_buffer_size"],
        expl_env,
        variant["algorithm_kwargs"]["max_path_length"] + 1,
        obs_dim,
        action_dim,
        replace=False,
        use_batch_length=use_batch_length,
        batch_length=50,
    )
    trainer_class_name = variant.get("algorithm", "DreamerV2")
    if trainer_class_name == "DreamerV2":
        trainer_class = DreamerV2Trainer
    elif trainer_class_name == "DreamerV2MCTS":
        trainer_class = DreamerV2MCTSTrainer
    else:
        trainer_class = DreamerTrainer
    trainer = trainer_class(
        eval_env,
        actor,
        vf,
        target_vf,
        world_model,
        eval_envs[0].image_shape,
        **variant["trainer_kwargs"],
    )
    algorithm = TorchBatchRLAlgorithm(
        trainer=trainer,
        exploration_env=expl_env,
        evaluation_env=eval_env,
        exploration_data_collector=expl_path_collector,
        evaluation_data_collector=eval_path_collector,
        replay_buffer=replay_buffer,
        pretrain_policy=rand_policy,
        **variant["algorithm_kwargs"],
    )
    trainer.pretrain_actor_vf(variant.get("num_actor_vf_pretrain_iters", 0))
    if variant.get("save_video", False):
        algorithm.post_epoch_funcs.append(video_post_epoch_func)
    algorithm.to(ptu.device)
    algorithm.train()
    if variant.get("save_video", False):
        video_post_epoch_func(algorithm, -1)
