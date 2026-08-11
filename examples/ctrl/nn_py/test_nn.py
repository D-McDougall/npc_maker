from npc_maker.ctrl import Controller
from pathlib import Path
import json

ctrl_prog_py = Path(__file__).parent.joinpath("nn.py")
ctrl_prog_rs = Path(__file__).parent.parent.joinpath("nn_rs").joinpath("target").joinpath("release").joinpath("nn")

genome = json.dumps([
    {
        "name": 0,
        "type": "Node",
        "slope": 10,
        "midpoint": 0.5
    },
    {
        "name": 1,
        "type": "Node",
        "slope": 10,
        "midpoint": 0.5
    },
    {
        "name": 2,
        "type": "Edge",
        "presyn": 0,
        "postsyn": 1,
        "weight": 2
    }
])

def test_nn():
    for ctrl_prog in [ctrl_prog_py, ctrl_prog_rs]:
        print(ctrl_prog)
        x = Controller("my_env", "my_pop", [ctrl_prog])
        x.genome(genome)
        x.set_input(0, 42)
        x.advance(0.01)
        assert x.is_alive()
        assert float(x.get_outputs(0)) < .001
        assert float(x.get_outputs(1)) > .999
        assert float(x.get_outputs(1)) > .999
        x.reset()
        x.advance(0.01)
        assert float(x.get_outputs(1)) < .001
        del x

if __name__ == "__main__":
    test_nn()
