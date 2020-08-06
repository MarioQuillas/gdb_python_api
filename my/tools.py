import gdb

class SwitchBreaker(gdb.Command):
  def __init__(self):
    super().__init__(
      'break-switch',
      gdb.COMMAND_RUNNING,
      gdb.COMPLETE_NONE,
      False
    )
  def invoke(self, arg, from_tty):
    frame = gdb.selected_frame()
    # TODO make this work if there is no debugging information, where .block() fails.
    block = frame.block()
    # Find the function block in case we are in an inner block.
    while block:
      if block.function:
        break
      block = block.superblock
    start = block.start
    end = block.end
    arch = frame.architecture()
    pc = gdb.selected_frame().pc()
    instructions = arch.disassemble(start, end - 1)
    for instruction in instructions:
      if instruction['asm'].startswith('jmpq '):
        gdb.Breakpoint('*{}'.format(instruction['addr']))
SwitchBreaker()
