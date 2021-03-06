import chainer
import chainer.functions as F

from become_yukarin.config.config import LossConfig
from become_yukarin.model.model import Discriminator
from become_yukarin.model.model import Predictor


class Updater(chainer.training.StandardUpdater):
    def __init__(
            self,
            loss_config: LossConfig,
            predictor: Predictor,
            discriminator: Discriminator,
            *args,
            **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.loss_config = loss_config
        self.predictor = predictor
        self.discriminator = discriminator

    def _loss_predictor(self, predictor, output, target, d_fake):
        b, _, t = d_fake.data.shape

        loss_mse = (F.mean_absolute_error(output, target))
        chainer.report({'mse': loss_mse}, predictor)

        loss_adv = F.sum(F.softplus(-d_fake)) / (b * t)
        chainer.report({'adversarial': loss_adv}, predictor)

        loss = self.loss_config.mse * loss_mse + self.loss_config.adversarial * loss_adv
        chainer.report({'loss': loss}, predictor)
        return loss

    def _loss_discriminator(self, discriminator, d_real, d_fake):
        b, _, t = d_real.data.shape

        loss_real = F.sum(F.softplus(-d_real)) / (b * t)
        chainer.report({'real': loss_real}, discriminator)

        loss_fake = F.sum(F.softplus(d_fake)) / (b * t)
        chainer.report({'fake': loss_fake}, discriminator)

        loss = loss_real + loss_fake
        chainer.report({'loss': loss}, discriminator)

        tp = (d_real.data > 0.5).sum()
        fp = (d_fake.data > 0.5).sum()
        fn = (d_real.data <= 0.5).sum()
        tn = (d_fake.data <= 0.5).sum()
        accuracy = (tp + tn) / (tp + fp + fn + tn)
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        chainer.report({'accuracy': accuracy}, self.discriminator)
        chainer.report({'precision': precision}, self.discriminator)
        chainer.report({'recall': recall}, self.discriminator)
        return loss

    def forward(self, input, target, mask):
        input = chainer.as_variable(input)
        target = chainer.as_variable(target)
        mask = chainer.as_variable(mask)

        output = self.predictor(input)
        output = output * mask
        target = target * mask

        d_fake = self.discriminator(input, output)
        d_real = self.discriminator(input, target)

        loss = {
            'predictor': self._loss_predictor(self.predictor, output, target, d_fake),
            'discriminator': self._loss_discriminator(self.discriminator, d_real, d_fake),
        }
        return loss

    def update_core(self):
        opt_predictor = self.get_optimizer('predictor')
        opt_discriminator = self.get_optimizer('discriminator')

        batch = self.get_iterator('main').next()
        batch = self.converter(batch, self.device)
        loss = self.forward(**batch)

        opt_predictor.update(loss.get, 'predictor')
        opt_discriminator.update(loss.get, 'discriminator')
