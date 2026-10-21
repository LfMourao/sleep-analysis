import re
import socket
import unittest

from sleep_analysis.serve import HOST, port_is_free, report_url


class PortTests(unittest.TestCase):
    def test_listening_port_is_busy_and_released_port_is_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind((HOST, 0))
            server.listen()
            port = server.getsockname()[1]
            self.assertFalse(port_is_free(port))
        self.assertTrue(port_is_free(port))


class UrlTests(unittest.TestCase):
    def test_url_points_to_the_page_and_busts_the_cache(self):
        self.assertRegex(report_url(8765), re.escape("http://127.0.0.1:8765/comparativo.html?v=") + r"\d{14}$")


if __name__ == "__main__":
    unittest.main()
