use npc_maker::ctrl::Controller;
use npc_maker::env;
use std::io::ErrorKind;

fn xor_test(ctrl: &mut Controller, verbose: bool) -> f64 {
    let mut distance: f64 = 0.0;
    for input_1 in 0..=1 {
        for input_2 in 0..=1 {
            ctrl.reset().unwrap();
            let mut prev = None;
            let mut steadystate = false;
            for _ in 0..4 {
                ctrl.set_input(0, &format!("{input_1}")).unwrap();
                ctrl.set_input(1, &format!("{input_2}")).unwrap();
                ctrl.advance(1.0).unwrap();
                let output: f64 = ctrl.get_outputs(&[2]).unwrap()[&2].parse().unwrap();
                if Some(output) == prev {
                    if verbose {
                        eprintln!("{input_1} xor {input_2} = {output}")
                    };
                    let correct: f64 = (input_1 != input_2) as i64 as f64;
                    distance += (correct - output).abs();
                    steadystate = true;
                    break;
                }
                prev = Some(output);
            }
            if !steadystate {
                return f64::NAN;
            }
        }
    }
    let score = (4.0 - distance).powi(2);
    if verbose {
        eprintln!("score {score}")
    };
    score
}

fn main() {
    let (env_spec, mode, _settings) = env::get_args();

    let mut ctrl: Option<Controller> = None;

    loop {
        env::spawn("xor");

        let result = env::input();
        if let Err(error) = &result {
            if error.kind() == ErrorKind::UnexpectedEof {
                break;
            } else {
                panic!("{}", error);
            }
        }
        let (indiv, genome) = result.unwrap();

        if let Some(ctrl) = &ctrl {
            assert_eq!(ctrl.get_command(), indiv.controller);
        } else {
            ctrl = Some(Controller::new(&env_spec.spec, "xor", indiv.controller).unwrap());
        }
        let ctrl = ctrl.as_mut().unwrap();

        ctrl.genome(&genome).unwrap();

        let score = xor_env(ctrl, mode == env::Mode::Graphical);

        env::score(&indiv.name, &score.to_string());

        env::death(&indiv.name);
    }
}
