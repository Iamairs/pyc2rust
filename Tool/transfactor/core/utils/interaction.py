

def wait_for_input(prompt: str):
    """等待用户输入。"""

    user_input = input(prompt)
    return user_input

def wait_for_choice(prompt: str, choices: list[str]):
    """等待用户选择。"""
    choices_prompt = "\n".join([f"{i}. {choice}" for i, choice in enumerate(choices, start=1)])
    accept_choices_indexes = [str(i) for i in range(1, len(choices) + 1)]
    accept_choices_indexes_str = "/".join(accept_choices_indexes)
    prompt = f"{prompt}\n{choices_prompt}\n"
    print(prompt)
    user_input = input(f"Please enter your choice[{accept_choices_indexes_str}]: ").lower()
    # len(all_accept_choices) == 2 * len(choices)
    all_accept_choices = [accept_choices_indexes] + [choice.lower() for choice in choices]
    while user_input not in all_accept_choices:
        user_input = input(f"Invalid choice, please enter again[{accept_choices_indexes_str}]: ")
    if user_input in accept_choices_indexes:
        return int(user_input) - 1, choices[int(user_input) - 1]
    else:
        return choices.index(user_input), user_input

if __name__ == '__main__':

    wait_for_choice(f"find existing projects in database, which one do you want to load?", [
        "project.name | project.create_time | project.description"
    ] + ["new project"])