"""
Tests for `dlgr.griduniverse` module.
"""
import collections
import json
import mock
import pytest
import time


class TestDependenciesLoaded(object):

    def test_tablib_importable(self):
        import tablib
        assert tablib is not None


@pytest.mark.usefixtures('env')
class TestExperimentClass(object):

    def test_initialization(self, exp):
        from dallinger.experiment import Experiment
        assert isinstance(exp, Experiment)

    def test_recruiter_property_is_some_subclass_of_recruiter(self, exp):
        from dallinger.recruiters import Recruiter
        assert isinstance(exp.recruiter, Recruiter)

    def test_new_experiment_has_a_grid(self, exp):
        from dlgr.griduniverse.experiment import Gridworld
        assert isinstance(exp.grid, Gridworld)

    def test_create_network_builds_default_network_type(self, exp):
        from dallinger.networks import FullyConnected
        net = exp.create_network()
        assert isinstance(net, FullyConnected)

    def test_session_is_dallinger_global(self, exp, db_session):
        assert exp.session() is db_session()

    def test_socket_session_is_not_dallinger_global(self, exp, db_session):
        # Experiment creates socket_session
        assert exp.socket_session() is not db_session()

    def test_environment_uses_experiments_networks(self, exp):
        exp.environment.network in exp.networks()

    def test_recruit_does_not_raise(self, exp):
        exp.recruit()

    def test_bonus(self, participants, exp):
        # With no experiment state, bonus returns 0
        assert exp.bonus(participants[0]) == 0.0

        with mock.patch('dlgr.griduniverse.experiment.Griduniverse.environment') as env:
            state_mock = mock.Mock()
            env.state.return_value = state_mock
            # State contents is JSON grid state
            state_mock.contents = '{"players": [{"id": "1", "payoff": 100.0}]}'
            assert exp.bonus(participants[0]) == 100.0


@pytest.mark.usefixtures('env', 'fake_gsleep')
class TestGameLoops(object):

    @pytest.fixture
    def loop_exp_3x(self, exp):
        exp.grid = mock.Mock()
        exp.grid.num_food = 10
        exp.grid.round = 0
        exp.grid.seasonal_growth_rate = 1
        exp.grid.food_growth_rate = 1.0
        exp.grid.rows = exp.grid.columns = 25
        exp.grid.players = {'1': mock.Mock()}
        exp.grid.players['1'].score = 10
        exp.grid.contagion = 1
        exp.grid.tax = 1.0
        exp.grid.food_locations = []
        exp.grid.frequency_dependence = 1
        exp.grid.frequency_dependent_payoff_rate = 0
        exp.grid.start_timestamp = time.time()
        exp.socket_session = mock.Mock()
        exp.publish = mock.Mock()
        exp.grid.serialize.return_value = {}

        def count_down(counter):
            for c in counter:
                return False
            return True
        end_counter = (i for i in range(3))
        start_counter = (i for i in range(3))
        # Each of these will loop three times before while condition is met
        type(exp.grid).game_started = mock.PropertyMock(
            side_effect=lambda: count_down(start_counter)
        )
        type(exp.grid).game_over = mock.PropertyMock(
            side_effect=lambda: count_down(end_counter)
        )
        yield exp

    def test_loop_builds_labrynth(self, loop_exp_3x):
        exp = loop_exp_3x
        exp.game_loop()
        # labryinth built once
        assert exp.grid.build_labyrinth.call_count == 1

    def test_loop_spawns_food(self, loop_exp_3x):
        exp = loop_exp_3x
        exp.game_loop()
        # Spawn food called once for each num_food
        assert exp.grid.spawn_food.call_count == exp.grid.num_food

    def test_loop_spawns_food_during_timed_events(self, loop_exp_3x):
        # Spawn food called twice for each num_food, once at start and again
        # on timed events to replenish empty list
        exp = loop_exp_3x

        # Ensure one timed events round
        exp.grid.start_timestamp -= 2

        exp.game_loop()
        assert exp.grid.spawn_food.call_count == exp.grid.num_food * 2

    def test_loop_serialized_and_saves(self, loop_exp_3x):
        # Grid serialized and added to DB session once per loop
        exp = loop_exp_3x
        exp.game_loop()
        assert exp.grid.serialize.call_count == 3
        assert exp.socket_session.add.call_count == 3
        # Session commited once per loop and again at end
        assert exp.socket_session.commit.call_count == 4

    def test_loop_resets_state(self, loop_exp_3x):
        # Wall and food state unset, food count reset during loop
        exp = loop_exp_3x
        exp.game_loop()
        assert exp.grid.walls_updated is False
        assert exp.grid.food_updated is False

    def test_loop_taxes_points(self, loop_exp_3x):
        # Player is taxed one point during the timed event round
        exp = loop_exp_3x

        # Ensure one timed events round
        exp.grid.start_timestamp -= 2

        exp.game_loop()
        assert exp.grid.players['1'].score == 9.0

    def test_loop_computes_payoffs(self, loop_exp_3x):
        # Payoffs computed once per loop before checking round completion
        exp = loop_exp_3x
        exp.game_loop()
        assert exp.grid.compute_payoffs.call_count == 3
        assert exp.grid.check_round_completion.call_count == 3

    def test_loop_publishes_stop_event(self, loop_exp_3x):
        # publish called with stop event at end of round
        exp = loop_exp_3x
        exp.game_loop()
        exp.publish.assert_called_once_with({'type': 'stop'})

    def test_send_state_thread(self, loop_exp_3x):
        # State thread will loop 4 times before the loop is broken
        exp = loop_exp_3x
        exp.grid.serialize.return_value = {
            'grid': 'serialized',
            'walls': [],
            'food': [],
            'players': [{'id': '1'}],
        }

        exp.send_state_thread()
        # Grid serialized once per loop
        assert exp.grid.serialize.call_count == 4
        # publish called with grid state message once per loop
        assert exp.publish.call_count == 4


@pytest.mark.usefixtures('env')
class TestPlayerConnects(object):

    def test_handle_connect_creates_node(self, exp, a):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})
        assert participant.id in exp.node_by_player_id

    def test_handle_connect_adds_player_to_grid(self, exp, a):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})
        assert participant.id in exp.grid.players

    def test_handle_connect_is_noop_for_spectators(self, exp):
        exp.handle_connect({'player_id': 'spectator'})
        assert exp.node_by_player_id == {}

    def test_colors_distributed_evenly(self, exp, participants):
        exp.grid.num_players = 9
        exp.networks()[0].max_size = 10
        players = [
            exp.handle_connect({'player_id': participant.id}) or exp.grid.players[participant.id]
            for participant in participants[:9]
        ]
        colors = collections.Counter([player.color_idx for player in players])
        assert colors == {0: 3, 1: 3, 2: 3}

    def test_colors_distributed_almost_evenly_if_on_edge(self, exp, participants):
        exp.grid.num_colors = 2
        exp.grid.num_players = 9
        exp.networks()[0].max_size = 10
        players = [
            exp.handle_connect({'player_id': participant.id}) or exp.grid.players[participant.id]
            for participant in participants[:9]
        ]
        colors = collections.Counter([player.color_idx for player in players])
        assert colors == {0: 5, 1: 4}


@pytest.mark.usefixtures('env')
class TestRecordPlayerActivity(object):

    def test_records_player_events(self, exp, a):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})
        exp.send(
            'griduniverse_ctrl:'
            '{{"type":"move","player_id":{},"move":"left"}}'.format(participant.id)
        )
        time.sleep(10)
        data = exp.retrieve_data()
        # Get the last recorded event
        event_detail = json.loads(data.infos.df['details'].values[-1])
        assert event_detail['player_id'] == participant.id
        assert event_detail['move'] == 'left'

    def test_scores_and_payoffs_averaged(self, exp, a):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})
        exp.send(
            'griduniverse_ctrl:'
            '{{"type":"move","player_id":{},"move":"left"}}'.format(participant.id)
        )
        time.sleep(10)
        data = exp.retrieve_data()
        results = json.loads(exp.analyze(data))
        assert results[u'average_score'] >= 0.0
        assert results[u'average_payoff'] >= 0.0

    def test_record_event_with_participant(self, exp, a):
        # Adds event to player node
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})
        exp.socket_session.add = mock.Mock()
        exp.socket_session.commit = mock.Mock()
        exp.record_event({'data': ['some data']},
                         player_id=participant.id)
        exp.socket_session.add.assert_called_once()
        exp.socket_session.commit.assert_called_once()
        info = exp.socket_session.add.call_args[0][0]
        assert info.details['data'] == ['some data']
        assert info.origin.id == exp.node_by_player_id[participant.id]

    def test_record_event_without_participant(self, exp):
        # Adds event to enviroment node
        node = exp.environment
        exp.socket_session.add = mock.Mock()
        exp.socket_session.commit = mock.Mock()
        exp.record_event({'data': ['some data']})
        exp.socket_session.add.assert_called_once()
        exp.socket_session.commit.assert_called_once()
        info = exp.socket_session.add.call_args[0][0]
        assert info.details['data'] == ['some data']
        assert info.origin.id == node.id

    def test_record_event_with_failed_node(self, exp, a):
        # Does not save event, but logs failure
        node = exp.environment
        node.failed = True
        exp.socket_session.add = mock.Mock()
        exp.socket_session.commit = mock.Mock()
        with mock.patch('dlgr.griduniverse.experiment.logger.info') as logger:
            exp.record_event({'data': ['some data']})
            assert exp.socket_session.add.call_count == 0
            assert exp.socket_session.commit.call_count == 0
            logger.assert_called_once()
            assert logger.call_args.startswith(
                'Tried to record an event after node#{} failure:'.format(
                    node.id
                )
            )


@pytest.mark.usefixtures('env')
class TestChat(object):

    def test_appends_to_chat_history(self, exp, a):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})

        exp.send(
            'griduniverse_ctrl:'
            '{{"type":"chat","player_id":{},"contents":"hello!"}}'.format(participant.id)
        )

        history = exp.grid.chat_message_history
        assert len(history) == 1
        assert 'hello!' in history[0]

    def test_republishes_non_broadcasts(self, exp, a, pubsub):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})

        exp.send(
            'griduniverse_ctrl:'
            '{{"type":"chat","player_id":{},"contents":"hello!"}}'.format(participant.id)
        )

        pubsub.publish.assert_called()

    def test_does_not_republish_broadcasts(self, exp, a, pubsub):
        participant = a.participant()
        exp.handle_connect({'player_id': participant.id})

        exp.send(
            'griduniverse_ctrl:'
            '{{"type":"chat","player_id":{},"contents":"hello!","broadcast":"true"}}'.format(
                participant.id
            )
        )

        pubsub.publish.assert_not_called()


@pytest.mark.usefixtures('env')
class TestDonation(object):

    def test_group_donations_distributed_evenly_across_team(self, exp, a):
        donor = a.participant()
        teammate = a.participant()
        exp.handle_connect({'player_id': donor.id})
        exp.handle_connect({'player_id': teammate.id})
        donor_player = exp.grid.players[1]
        teammate_player = exp.grid.players[2]
        # put them on the same team:
        exp.handle_change_color(
            {
                'player_id': teammate_player.id,
                'color': donor_player.color
            }
        )
        # make donation active
        exp.grid.donation_group = True
        exp.grid.donation_amount = 1
        donor_player.score = 2

        exp.handle_donation(
            {
                'donor_id': donor_player.id,
                'recipient_id': 'group:{}'.format(donor_player.color_idx),
                'amount': 2
            }
        )
        assert donor_player.score == 1
        assert teammate_player.score == 1

    def test_public_donations_distributed_evenly_across_players(self, exp, a):
        donor = a.participant()
        opponent = a.participant()
        exp.handle_connect({'player_id': donor.id})
        exp.handle_connect({'player_id': opponent.id})
        donor_player = exp.grid.players[1]
        opponent_player = exp.grid.players[2]
        exp.grid.donation_public = True
        exp.grid.donation_amount = 1
        donor_player.score = 2

        exp.handle_donation(
            {
                'donor_id': donor_player.id,
                'recipient_id': 'all',
                'amount': 2
            }
        )

        assert donor_player.score == 1
        assert opponent_player.score == 1
