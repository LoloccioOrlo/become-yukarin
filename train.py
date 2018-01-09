import argparse
from functools import partial
from pathlib import Path

from chainer import cuda
from chainer import optimizers
from chainer import training
from chainer.dataset import convert
from chainer.iterators import MultiprocessIterator
from chainer.training import extensions

from become_yukarin.config import create_from_json
from become_yukarin.dataset import create as create_dataset
from become_yukarin.updater import Updater
from become_yukarin.model import create

parser = argparse.ArgumentParser()
parser.add_argument('config_json_path', type=Path)
parser.add_argument('output', type=Path)
arguments = parser.parse_args()

config = create_from_json(arguments.config_json_path)
arguments.output.mkdir(exist_ok=True)
config.save_as_json((arguments.output / 'config.json').absolute())

# model
if config.train.gpu >= 0:
    cuda.get_device_from_id(config.train.gpu).use()
predictor, aligner, discriminator = create(config.model)
models = {'predictor': predictor}
if aligner is not None:
    models['aligner'] = aligner
if discriminator is not None:
    models['discriminator'] = discriminator

# dataset
dataset = create_dataset(config.dataset)
train_iter = MultiprocessIterator(dataset['train'], config.train.batchsize)
test_iter = MultiprocessIterator(dataset['test'], config.train.batchsize, repeat=False, shuffle=False)
train_eval_iter = MultiprocessIterator(dataset['train_eval'], config.train.batchsize, repeat=False, shuffle=False)


# optimizer
def create_optimizer(model):
    optimizer = optimizers.Adam()
    optimizer.setup(model)
    return optimizer


opts = {key: create_optimizer(model) for key, model in models.items()}

# updater
converter = partial(convert.concat_examples, padding=0)
updater = Updater(
    loss_config=config.loss,
    model_config=config.model,
    predictor=predictor,
    aligner=aligner,
    discriminator=discriminator,
    device=config.train.gpu,
    iterator=train_iter,
    optimizer=opts,
    converter=converter,
)

# trainer
trigger_log = (config.train.log_iteration, 'iteration')
trigger_snapshot = (config.train.snapshot_iteration, 'iteration')

trainer = training.Trainer(updater, out=arguments.output)

ext = extensions.Evaluator(test_iter, models, converter, device=config.train.gpu, eval_func=updater.forward)
trainer.extend(ext, name='test', trigger=trigger_log)
ext = extensions.Evaluator(train_eval_iter, models, converter, device=config.train.gpu, eval_func=updater.forward)
trainer.extend(ext, name='train', trigger=trigger_log)

trainer.extend(extensions.dump_graph('predictor/loss', out_name='graph.dot'))

ext = extensions.snapshot_object(predictor, filename='predictor_{.updater.iteration}.npz')
trainer.extend(ext, trigger=trigger_snapshot)

trainer.extend(extensions.LogReport(trigger=trigger_log, log_name='log.txt'))

if extensions.PlotReport.available():
    trainer.extend(extensions.PlotReport(
        y_keys=[
            'predictor/loss',
            'predictor/l1',
            'test/predictor/loss',
            'train/predictor/loss',
            'discriminator/accuracy',
            'discriminator/fake',
            'discriminator/true',
            'discriminator/grad',
        ],
        x_key='iteration',
        file_name='loss.png',
        trigger=trigger_log,
    ))

trainer.run()
