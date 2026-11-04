from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0058_poker_chip_wallet')]
    operations = [
        migrations.AddField(
            model_name='extensionresource', name='category',
            field=models.CharField(choices=[('library', '资料库'), ('games', '小游戏')], default='library', max_length=16),
        ),
        migrations.CreateModel(name='BuiltinExtensionCategory', fields=[
            ('key', models.CharField(max_length=40, primary_key=True, serialize=False)),
            ('category', models.CharField(choices=[('library', '资料库'), ('games', '小游戏')], default='games', max_length=16)),
        ]),
    ]
