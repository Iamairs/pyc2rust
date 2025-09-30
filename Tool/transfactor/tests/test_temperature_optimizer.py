import unittest
from unittest.mock import patch
import numpy as np
from core.utils.optimizer import TemperatureOptimizer  # 根据实际情况修改导入路径


class TestTemperatureOptimizer(unittest.TestCase):
    def setUp(self):
        self.initial_temp = 0.4
        self.min_temp = 0.0
        self.max_temp = 1.3
        self.step = 0.01
        self.sigma = 0.1
        self.optimizer = TemperatureOptimizer(
            initial_temp=self.initial_temp,
            min_temp=self.min_temp,
            max_temp=self.max_temp,
            step=self.step,
            sigma=self.sigma
        )

    def test_initialization(self):
        """测试初始化参数是否正确赋值"""
        self.assertEqual(self.optimizer.initial_temp, self.initial_temp)
        self.assertEqual(self.optimizer.current_temp, self.initial_temp)
        self.assertEqual(self.optimizer.min_temp, self.min_temp)
        self.assertEqual(self.optimizer.max_temp, self.max_temp)
        self.assertEqual(self.optimizer.step, self.step)
        self.assertEqual(self.optimizer.sigma, self.sigma)

    @patch('numpy.random.normal')
    def test_do_sample_basic(self, mock_normal):
        """测试 do_sample 返回正确数量的样本并在范围内"""
        # 假设产生的随机数序列为可控值（重复两次同样的值，以便测试不重复逻辑）
        # 这里手动指定一个样本序列模拟随机结果
        mock_normal.side_effect = [0.4, 0.4, 0.45, 1.5, -0.1, 0.39, 1.3]

        # 请求 2 个样本
        samples = self.optimizer.do_sample(num_samples=2)

        # 检查样本数量为2
        self.assertEqual(len(samples), 2)

        # 检查样本范围在 min_temp 到 max_temp 之间
        for s in samples:
            self.assertTrue(self.min_temp <= s <= self.max_temp)

        # 检查不重复性和正确性（根据 side_effect 筛选通过的应为0.4,0.45或0.39,1.3之类的值）
        # given side_effect的逻辑： 
        # - 第一次:0.4 （valid） 
        # - 第二次:0.4 （重复，跳过） 
        # - 第三次:0.45（valid）
        # 若已满足2个样本(0.4与0.45)则直接结束
        expected_samples = [0.4, 0.45]
        self.assertListEqual(samples, expected_samples)

    @patch('numpy.random.normal')
    def test_do_sample_all_out_of_range(self, mock_normal):
        """测试当随机数全部超出范围时，依旧能够继续尝试，直到得到合规样本"""
        # 以下序列前三个都超出范围(1.5,1.6,-0.2)，直到最后给出0.3才返回
        mock_normal.side_effect = [1.5, 1.6, -0.2, 0.3]
        samples = self.optimizer.do_sample(num_samples=1)
        self.assertEqual(samples, [0.3])

    def test_update_increase(self):
        """测试update，当传入温度比current_temp高时，应向上调整"""
        self.optimizer.current_temp = 0.4
        new_temp = self.optimizer.update(0.5)
        self.assertEqual(new_temp, 0.4 + self.step)
        self.assertEqual(self.optimizer.current_temp, 0.4 + self.step)

    def test_update_decrease(self):
        """测试update，当传入温度比current_temp低时，应向下调整"""
        self.optimizer.current_temp = 0.4
        new_temp = self.optimizer.update(0.3)
        self.assertEqual(new_temp, 0.4 - self.step)
        self.assertEqual(self.optimizer.current_temp, 0.4 - self.step)

    def test_update_no_change(self):
        """测试update，当传入温度等于current_temp时，无需调整"""
        self.optimizer.current_temp = 0.4
        new_temp = self.optimizer.update(0.4)
        self.assertEqual(new_temp, 0.4)
        self.assertEqual(self.optimizer.current_temp, 0.4)

    def test_update_to_minimum(self):
        """测试update，当向下调整超过最小值时，应被限制在最小值"""
        self.optimizer.current_temp = 0.01
        new_temp = self.optimizer.update(-0.1)
        self.assertEqual(new_temp, self.min_temp)
        self.assertEqual(self.optimizer.current_temp, self.min_temp)

    def test_update_to_maximum(self):
        """测试update，当向上调整超过最大值时，应被限制在最大值"""
        self.optimizer.current_temp = 1.29
        new_temp = self.optimizer.update(2.0)
        self.assertEqual(new_temp, self.max_temp)
        self.assertEqual(self.optimizer.current_temp, self.max_temp)


if __name__ == '__main__':
    unittest.main()
