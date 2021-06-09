import torch
import torchvision
import torch.nn.functional as F


# writer = SummaryWriter()

def train(models, train_loader, val_loader, criterion, model_path, num_epochs, device):
    model = models
    num_epochs = num_epochs
    model_path = model_path
    lr = 1
    criterion = criterion
    train_loader = train_loader
    val_loader = val_loader
    device = device
    optimizers = torch.optim.Adadelta(model.parameters(), lr=lr)

    for epoch in range(25):
        print("Train : " + str(epoch) + "=======")
        running_loss = 0.0
        for i_batch, (avg, mot, lab) in enumerate(train_loader):

            optimizers.zero_grad()
            avg, mot, lab = avg.to(device), mot.to(device), lab.to(device)
            model.forward(avg, mot)

            if i_batch is 0 and epoch is 0:
                # writer.add_graph(self.model, (avg, mot))
                images = F.interpolate(avg[:10], 128)
                img_grid = torchvision.utils.make_grid(images, nrow=10)
                # writer.add_image('avg', img_grid)
                images = F.interpolate(mot[:10], 128)
                mot_grid = torchvision.utils.make_grid(images, nrow=10)
                # writer.add_image('mot', mot_grid)

            output = model(avg, mot)
            if i_batch is 0:
                mask1, mask2 = model.appearance_model(avg)
                # writer.add_image('mask1', mask1[0], epoch)
                # writer.add_image('mask2', mask2[0], epoch)
            loss = criterion(output, lab)
            loss.backward()
            running_loss += loss.item()
            optimizers.step()
            # if i_batch is 0:
            # writer.add_scalar('training loss', running_loss, epoch)
            # writer.add_scalar('training loss',running_loss / 128 ,epoch * len(train_loader) + i_batch)
        with torch.no_grad():
            val_loss = 0.0
            for k, (avg, mot, lab) in enumerate(val_loader):
                avg, mot, lab = avg.to(device), mot.to(device), lab.to(device)
                if name.find("TS") is not -1:
                    if avg.shape[0] % 2 is 1:  # TS network need 2 images
                        continue
                val_output = model(avg, mot)
                v_loss = criterion(val_output, lab)
                val_loss += v_loss
                if k is 0:
                    # writer.add_scalar('val loss', v_loss, epoch)
                    if tmp_valloss > val_loss:
                        checkpoint = {'Epoch': epoch,
                                      'state_dict': model.state_dict(),
                                      'optimizer': optimizers.state_dict()}
                        torch.save(checkpoint, 'checkpoint_train.pth')
                        tmp_valloss = val_loss
                # writer.add_scalar('val loss', val_loss / 128, epoch * len(val_loader) + i_batch)
        # writer.close()
    print('Finished Training')
