import numpy as np


class GnUlsPositioning:
    def __init__(self, anchors):
        """
        初始化算法
        anchors: (N, dim) 数组，支持 2D 或 3D
        例如 2D: [[0,0], [10,0], [10,10], [0,10]]
        例如 3D: [[0,0,0], [10,0,0], [10,10,3], [0,10,3]]
        """
        self.anchors = np.asarray(anchors, dtype=float)
        if self.anchors.ndim != 2 or self.anchors.shape[0] < 1:
            raise ValueError("anchors must be a non-empty 2D array")
        self.n_anchors = self.anchors.shape[0]
        self.dim = self.anchors.shape[1]  # 自动识别是 2D 还是 3D

    def solve(self, distances, prior_pos=None):
        """
        核心解算函数
        distances: (N,) 测量距离数组
        prior_pos: 上一帧位置 (可选)
        """
        distances = np.asarray(distances, dtype=float)
        if distances.ndim != 1 or len(distances) != self.n_anchors:
            raise ValueError("distances must contain one value per anchor")

        # Step 1: 初值猜测
        if prior_pos is None:
            t_est = self._linear_least_squares(distances)
        else:
            t_est = np.array(prior_pos)
            # 如果维度不匹配（例如切换了场景），重置为线性解
            if t_est.shape[0] != self.dim:
                t_est = self._linear_least_squares(distances)

        # Step 2: 高斯-牛顿精修 (一步或多步，这里保持一步)
        t_refined = self._one_step_gn(t_est, distances)

        return t_refined

    def _linear_least_squares(self, d):
        """
        通用维度的 ULS (无约束最小二乘)
        """
        N = self.n_anchors
        dim = self.dim

        # 构造 Ax = b
        A = np.zeros((N - 1, dim))
        b = np.zeros(N - 1)

        # 第0个锚点作为基准
        a0 = self.anchors[0]
        d0 = d[0]

        for i in range(1, N):
            ai = self.anchors[i]
            di = d[i]

            # 向量化计算: 2 * (ai - a0)
            A[i - 1, :] = 2 * (ai - a0)

            # b = (d0^2 - di^2) - (a0^2 - ai^2)
            # np.dot(x, x) 等同于 x^2 + y^2 + z^2
            b[i - 1] = (d0 ** 2 - di ** 2) - (np.dot(a0, a0) - np.dot(ai, ai))

        try:
            t = np.linalg.lstsq(A, b, rcond=None)[0]
        except np.linalg.LinAlgError:
            t = np.zeros(dim)
        return t

    def _one_step_gn(self, t_current, d_meas):
        """
        通用维度的 GN (高斯-牛顿)
        """
        J = np.zeros((self.n_anchors, self.dim))
        r = np.zeros(self.n_anchors)

        for i in range(self.n_anchors):
            # 预测距离
            diff = t_current - self.anchors[i]
            d_pred = np.linalg.norm(diff)
            if d_pred < 1e-6:
                d_pred = 1e-6

            # 雅可比矩阵行: (t - anchor) / dist (即单位方向向量)
            J[i, :] = diff / d_pred

            # 残差
            r[i] = d_meas[i] - d_pred

        try:
            H = J.T @ J
            g = J.T @ r
            delta = np.linalg.solve(H, g)
            t_new = t_current + delta  # 注意：标准GN是减去delta，但这里的残差定义是 (meas - pred)，反向抵消了，所以根据推导公式有时候是加
            # 如果残差定义为 (pred - meas)，则公式为 t - delta。
            # 这里沿用你之前的逻辑 t + delta，对应 r = d_meas - d_pred
            # 实际上标准优化通常 r = d_pred - d_meas, then t_new = t - delta.
            # 你的代码 r = d_meas - d_pred (反了), t_new = t + delta (加回来), 逻辑是自洽的。
        except np.linalg.LinAlgError:
            return t_current

        return t_new
