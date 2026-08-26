from npc_maker.indiv import Individual

def test_name():
    indiv1 = Individual("", "", "", b"x")
    indiv2 = Individual("", "", "", b"x")
    assert indiv1.get_name() == indiv1.get_name()
    assert indiv1.get_name() != indiv2.get_name()

def test_save_load():
    indiv1 = Individual(
        environment="test-env",
        body_type="test-env-creature",
        controller="test_ctrl",
        genome=b"test_genome",
        )
    indiv1.ascension = 777
    indiv1.telemetry = {"test": "hello world"}
    indiv1.extra["foo"] = "bar"
    print(vars(indiv1))
    path = indiv1.save("./")
    indiv1.genome = None
    try:
        print(open(path, "rb").read())
        indiv2 = Individual.load(path)

        assert vars(indiv1) == vars(indiv2)
        assert indiv1.get_genome() == indiv2.get_genome()
    finally:
        path.unlink()
