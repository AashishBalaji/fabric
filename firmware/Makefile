CC := arm-none-eabi-gcc
OBJCOPY := arm-none-eabi-objcopy
CFLAGS := -mcpu=cortex-m3 -mthumb -O2 -ffreestanding -nostdlib -fno-builtin \
          -Wall -Wextra -g
LDFLAGS := -T stellaris.ld -nostdlib -Wl,--gc-sections

OBJS := startup.o main.o

all: firmware.elf firmware.bin

%.o: %.c regs.h
	$(CC) $(CFLAGS) -c $< -o $@

firmware.elf: $(OBJS) stellaris.ld
	$(CC) $(CFLAGS) $(LDFLAGS) $(OBJS) -o $@

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f *.o firmware.elf firmware.bin

.PHONY: all clean
