from collections import deque, OrderedDict
from rlkit.core.eval_util import create_stats_ordered_dict
from rlkit.samplers.data_collector.base import PathCollector
from rlkit.torch.model_based.dreamer.rollout_functions import vec_rollout


class VecMdpPathCollector(PathCollector):
    def __init__(
        self,
        env,
        policy,
        max_num_epoch_paths_saved=None,
        render=False,
        render_kwargs=None,
        rollout_fn=vec_rollout,
        save_env_in_snapshot=True,
    ):
        if render_kwargs is None:
            render_kwargs = {}
        self._env = env
        self._policy = policy
        self._max_num_epoch_paths_saved = max_num_epoch_paths_saved
        self._epoch_paths = deque(maxlen=self._max_num_epoch_paths_saved)
        self._render = render
        self._render_kwargs = render_kwargs
        self._rollout_fn = rollout_fn

        self._num_steps_total = 0
        self._num_paths_total = 0

        self._save_env_in_snapshot = save_env_in_snapshot

    def collect_new_paths(
        self,
        max_path_length,
        num_steps,
        discard_incomplete_paths,
        runtime_policy=None,
    ):
        paths = []
        num_steps_collected = 0
        while num_steps_collected < num_steps:
            if not runtime_policy:
                runtime_policy = self._policy
            path = self._rollout_fn(
                self._env,
                runtime_policy,
                max_path_length=max_path_length,
                render=self._render,
                render_kwargs=self._render_kwargs,
            )
            path_len = len(path["actions"])
            num_steps_collected += path_len * self._env.n_envs
            paths.append(path)
        self._num_paths_total += len(paths) * self._env.n_envs
        self._num_steps_total += num_steps_collected
        log_paths = [{} for i in range(len(paths))]
        for i, path in enumerate(paths):
            for k in [
                "observations",
                "actions",
                "terminals",
                "rewards",
                "next_observations",
            ]:
                log_paths[i][k] = path[k][1:]
            for k in ["agent_infos", "env_infos"]:
                log_paths[i][k] = path[k][1:]
        self._epoch_paths.extend(log_paths)  # only used for logging
        return paths

    def get_epoch_paths(self):
        return self._epoch_paths

    def end_epoch(self, epoch):
        self._epoch_paths = deque(maxlen=self._max_num_epoch_paths_saved)

    def get_diagnostics(self):
        path_lens = [len(path["actions"]) for path in self._epoch_paths]
        stats = OrderedDict(
            [
                ("num steps total", self._num_steps_total),
                ("num paths total", self._num_paths_total),
            ]
        )
        stats.update(
            create_stats_ordered_dict(
                "path length",
                path_lens,
                always_show_all_stats=True,
            )
        )
        return stats

    def get_snapshot(self):
        snapshot_dict = dict(
            policy=self._policy,
        )
        if self._save_env_in_snapshot:
            snapshot_dict["env"] = self._env
        return snapshot_dict
